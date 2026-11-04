"""mm-disclosure 的离线契约检查。"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_plugin():
    spec = importlib.util.spec_from_file_location("mm_disclosure_under_test", PLUGIN_DIR / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PLUGIN = load_plugin()


class TestPlugin(unittest.TestCase):
    def test_rule_is_loaded_from_single_body(self):
        rule = (PLUGIN_DIR / "rule.md").read_text(encoding="utf-8").strip()
        self.assertEqual(PLUGIN.RULE, rule)
        self.assertLessEqual(len(rule), PLUGIN.MAX_CHARS)
        self.assertIn("等待返回后再调用相关任务工具", rule)
        self.assertNotIn("hermes-alice", rule)

    def test_platform_allowlist_accepts_any_profile(self):
        self.assertEqual(PLUGIN._rule_section({"profile_name": "anyone", "platform": "webui"}), PLUGIN.RULE)
        self.assertEqual(PLUGIN._rule_section({"profile_name": "anyone", "platform": "subagent"}), "")
        self.assertEqual(PLUGIN._rule_section({"profile_name": "anyone", "platform": "cron"}), "")
        self.assertEqual(PLUGIN._rule_section({"platform": "cli"}), PLUGIN.RULE)
        self.assertEqual(PLUGIN._rule_section({"platform": "tui"}), PLUGIN.RULE)
        self.assertEqual(PLUGIN._rule_section({}), "")
        self.assertIsNone(PLUGIN._pre_llm_call(is_first_turn=True, platform="subagent"))

    def test_index_uses_explicit_content_detail(self):
        index = PLUGIN._build_index([
            {"id": "demo", "name": "演示模型", "tags": ["when:演示任务前加载"], "last_refreshed_at": "2026-01-02"}
        ], {})
        self.assertIn('mental_model_id="<id>"', index)
        self.assertIn('detail="content"', index)
        self.assertIn("demo", index)

    def test_index_omits_bank_arg_when_bank_unset(self):
        index = PLUGIN._build_index([{"id": "demo"}], {}, bank_id=None)
        self.assertIn('get_mental_model(mental_model_id="<id>", detail="content")', index)
        self.assertNotIn('bank_id="', index)
        self.assertIn("bank_id 未配置", index)

    def test_index_carries_bank_when_configured(self):
        index = PLUGIN._build_index([{"id": "demo"}], {}, bank_id="my-bank")
        self.assertIn('get_mental_model(mental_model_id="<id>", bank_id="my-bank", detail="content")', index)
        self.assertNotIn("bank_id 未配置", index)

    def test_events_follow_active_hermes_home(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            constants = types.ModuleType("hermes_constants")
            constants.get_hermes_home = lambda: home
            with patch.dict(sys.modules, {"hermes_constants": constants}):
                PLUGIN._emit({"event": "probe"})
            path = home / "cache/mm-disclosure/events.jsonl"
            self.assertTrue(path.is_file())
            self.assertIn('"event": "probe"', path.read_text(encoding="utf-8"))

    def test_plugin_config_defaults_when_file_absent(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            constants = types.ModuleType("hermes_constants")
            constants.get_hermes_home = lambda: home
            with patch.dict(sys.modules, {"hermes_constants": constants}):
                cfg = PLUGIN._plugin_config()
        self.assertEqual(cfg, {"mcp_server": "hindsight-mcp", "bank_id": None, "error": None})

    def test_plugin_config_validates_fields(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            constants = types.ModuleType("hermes_constants")
            constants.get_hermes_home = lambda: home
            path = home / "mm-disclosure.json"
            with patch.dict(sys.modules, {"hermes_constants": constants}):
                path.write_text('{"bank_id": "my-bank"}', encoding="utf-8")
                self.assertEqual(PLUGIN._plugin_config()["bank_id"], "my-bank")
                path.write_text('{"mcp_server": "other-mcp"}', encoding="utf-8")
                self.assertEqual(PLUGIN._plugin_config()["mcp_server"], "other-mcp")
                path.write_text("not json", encoding="utf-8")
                self.assertEqual(PLUGIN._plugin_config()["error"], "config_invalid")
                path.write_text('{"bank_id": 42}', encoding="utf-8")
                self.assertEqual(PLUGIN._plugin_config()["error"], "config_invalid")
                path.write_text('[1, 2]', encoding="utf-8")
                self.assertEqual(PLUGIN._plugin_config()["error"], "config_invalid")

    def test_invalid_plugin_config_blocks_request(self):
        with patch.object(PLUGIN, "_plugin_config",
                          return_value={"mcp_server": "hindsight-mcp", "bank_id": None,
                                        "error": "config_invalid"}), \
             patch.object(PLUGIN, "_Hindsight") as mock_client:
            self.assertEqual(PLUGIN._list_mental_models(), [])
            mock_client.assert_not_called()

    def test_default_bank_omitted_and_explicit_bank_consistent(self):
        captured = []

        def fake_call(tool, arguments):
            captured.append(arguments)
            return {"items": [{"id": "m1"}]}

        def fake_client(server):
            return types.SimpleNamespace(url="https://example.test/mcp", call=fake_call)

        # bank 未配置：list_mental_models 不传 bank_id
        with patch.object(PLUGIN, "_plugin_config",
                          return_value={"mcp_server": "hindsight-mcp", "bank_id": None, "error": None}), \
             patch.object(PLUGIN, "_Hindsight", side_effect=fake_client):
            self.assertEqual(PLUGIN._list_mental_models(), [{"id": "m1"}])
        self.assertEqual(captured, [{"detail": "metadata"}])

        # bank 显式配置：list 调用与索引里的正文加载指引带同一 bank_id
        captured.clear()
        with patch.object(PLUGIN, "_plugin_config",
                          return_value={"mcp_server": "hindsight-mcp", "bank_id": "b1", "error": None}), \
             patch.object(PLUGIN, "_Hindsight", side_effect=fake_client):
            self.assertEqual(PLUGIN._list_mental_models(), [{"id": "m1"}])
        self.assertEqual(captured, [{"detail": "metadata", "bank_id": "b1"}])
        index = PLUGIN._build_index([{"id": "m1"}], {}, bank_id="b1")
        self.assertIn('bank_id="b1"', index)

    def test_auth_uses_effective_config_and_rejects_unresolved_secret(self):
        package = types.ModuleType("hermes_cli")
        package.__path__ = []
        config = types.ModuleType("hermes_cli.config")
        config.load_config_readonly = lambda: {"mcp_servers": {"hindsight-mcp": {
            "url": "https://example.test/mcp", "headers": {"Authorization": "Bearer test-only"}}}}
        with patch.dict(sys.modules, {"hermes_cli": package, "hermes_cli.config": config}):
            self.assertEqual(PLUGIN._read_hindsight_auth(), ("https://example.test/mcp", "Bearer test-only"))
            config.load_config_readonly = lambda: {"mcp_servers": {"hindsight-mcp": {
                "url": "https://example.test/mcp", "headers": {"Authorization": "Bearer ${env:MISSING}"}}}}
            self.assertEqual(PLUGIN._read_hindsight_auth(), ("", ""))
            # 无 Authorization 的服务允许请求
            config.load_config_readonly = lambda: {"mcp_servers": {"hindsight-mcp": {
                "url": "https://example.test/mcp"}}}
            self.assertEqual(PLUGIN._read_hindsight_auth(), ("https://example.test/mcp", ""))
            # 自定义连接名读取对应 mcp_servers 项
            config.load_config_readonly = lambda: {"mcp_servers": {"other-mcp": {
                "url": "https://other.test/mcp"}}}
            self.assertEqual(PLUGIN._read_hindsight_auth("other-mcp"), ("https://other.test/mcp", ""))

    def test_slow_index_is_bounded_and_does_not_queue_threads(self):
        release = threading.Event()
        started = threading.Event()

        def slow():
            started.set()
            release.wait(1)
            return [{"id": "late"}]

        try:
            with patch.object(PLUGIN, "_list_mental_models", side_effect=slow):
                models, error = PLUGIN._list_mental_models_bounded(0.01)
                self.assertTrue(started.is_set())
                self.assertEqual((models, error), ([], "index_timeout"))
                self.assertEqual(PLUGIN._list_mental_models_bounded(0.01), ([], "index_busy"))
        finally:
            release.set()
        self.assertTrue(PLUGIN._INDEX_LOCK.acquire(timeout=1))
        PLUGIN._INDEX_LOCK.release()

    def test_fetch_carries_context_to_worker(self):
        from contextvars import ContextVar
        scope = ContextVar("profile_secret_scope", default="missing")
        with patch.object(PLUGIN, "_list_mental_models", side_effect=lambda: [{"id": scope.get()}]):
            token = scope.set("profile-scoped")
            try:
                self.assertEqual(PLUGIN._list_mental_models_bounded(1), ([{"id": "profile-scoped"}], None))
            finally:
                scope.reset(token)

    def test_first_turn_fails_open_with_timeout_signal(self):
        release = threading.Event()
        events = []
        def slow(*_):
            release.wait(1)
            return []
        try:
            with patch.object(PLUGIN, "_INDEX_BUDGET", 0.02), \
                 patch.object(PLUGIN, "_plugin_config",
                              return_value={"mcp_server": "hindsight-mcp", "bank_id": None,
                                            "error": None}), \
                 patch.object(PLUGIN, "_load_model_registry", return_value={"fixture-default": {"default": True}}), \
                 patch.object(PLUGIN, "_list_mental_models", side_effect=slow), \
                 patch.object(PLUGIN, "_emit", side_effect=events.append):
                start = time.monotonic()
                index = PLUGIN._pre_llm_call(is_first_turn=True, platform="webui")
                self.assertIn("不完整", index["context"])
                self.assertIn("fixture-default", index["context"])
                self.assertLess(time.monotonic() - start, 0.2)
                self.assertEqual(events[-1]["error"], "index_timeout")
                self.assertTrue(events[-1]["partial"])
                self.assertEqual(events[-1]["model_count"], 1)
        finally:
            release.set()
        self.assertTrue(PLUGIN._INDEX_LOCK.acquire(timeout=1))
        PLUGIN._INDEX_LOCK.release()

    def test_first_turn_inject_records_config_error(self):
        events = []
        with patch.object(PLUGIN, "_plugin_config",
                          return_value={"mcp_server": "hindsight-mcp", "bank_id": None,
                                        "error": "config_invalid"}), \
             patch.object(PLUGIN, "_load_model_registry", return_value={"fixture-default": {"default": True}}), \
             patch.object(PLUGIN, "_emit", side_effect=events.append):
            index = PLUGIN._pre_llm_call(is_first_turn=True, platform="cli")
            self.assertIsNone(index)
            self.assertEqual(events[-1]["error"], "config_invalid")


if __name__ == "__main__":
    unittest.main()
