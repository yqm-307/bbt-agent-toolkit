"""custom-prompt-inject 的离线契约检查。

`user_context` 规则通过 pre_llm_call 返回给宿主，测试按真实载体记录
`api_content = 用户 content + 宿主追加区`，用户自己写入的正文不作投递证据。
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def load_plugin():
    spec = importlib.util.spec_from_file_location("custom_prompt_inject_under_test", PLUGIN_DIR / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


P = load_plugin()
SOL, CLAUDE, SWE = "gpt-6.1-sol", "claude-opus-5-5", "swe-2"
FAMILY = P._read("prompts/family/openai.md")
COMMON = P._read("prompts/family/subagent-prompt-common.md")


class TestPlugin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.secret_path = Path(self.tmp.name) / "secret"
        self.secret_patch = patch.object(P, "_secret_path", lambda: self.secret_path)
        self.secret_patch.start()
        self.addCleanup(self.secret_patch.stop)
        P._secret_cache = None
        self.addCleanup(setattr, P, "_secret_cache", None)
        self.history: dict[str, list[dict]] = {}

    def section(self, model, sid="s1", platform="webui"):
        return P._section({"session_id": sid, "model": model, "platform": platform})

    def turn(self, model, sid="s1", platform="webui"):
        history = self.history.setdefault(sid, [])
        out = P._pre_llm_call(session_id=sid, model=model, platform=platform,
                               conversation_history=history)
        context = (out or {}).get("context")
        if context:
            history.append({"role": "user", "content": "hi", "api_content": "hi\n\n" + context})
        return context

    def test_json_config_is_loaded_and_contains_explicit_targets(self):
        self.assertEqual(P.CONFIG_PATH.name, "config.json")
        self.assertGreaterEqual(len(P.RULES), 2)
        for rule in P.RULES:
            self.assertTrue(rule["id"])
            self.assertTrue(set(rule["inject_into"]) <= {"system_prompt", "user_context"})

    def test_subagent_rule_is_model_independent(self):
        for model in (SOL, "deepseek-flash", CLAUDE, SWE):
            self.assertEqual(self.section(model, platform="subagent"), COMMON)
            self.assertIn(COMMON, self.turn(model, sid=f"subagent-{model}", platform="subagent") or "")

    def test_model_regex_rule_only_matches_openai_names(self):
        for model in (SOL, "codex-mini", "openai/gpt-6.1-sol", "openai/codex-mini"):
            self.assertEqual(self.section(model), FAMILY)
        self.assertEqual(self.section(CLAUDE), "")
        self.assertEqual(self.section("deepseek-v4"), "")

    def test_conditions_support_exact_model_model_list_and_regex(self):
        rules = [
            {"id": "exact", "prompt": "prompts/family/openai.md", "inject_into": ["system_prompt"],
             "when": {"model": SOL}},
            {"id": "list", "prompt": "prompts/family/subagent-prompt-common.md", "inject_into": ["system_prompt"],
             "when": {"models": [CLAUDE, SWE]}},
            {"id": "regex", "prompt": "prompts/family/openai.md", "inject_into": ["system_prompt"],
             "when": {"model_regex": "^gpt-"}},
        ]
        with patch.object(P, "RULES", rules):
            self.assertEqual(self.section(SOL), FAMILY + "\n\n" + FAMILY)
            self.assertEqual(self.section(CLAUDE), COMMON)
            self.assertEqual(self.section(SWE), COMMON)
            self.assertEqual(self.section("gemini-3"), "")

    def test_conditions_are_combined_with_and(self):
        rule = {"id": "combined", "prompt": "prompts/family/openai.md", "inject_into": ["system_prompt"],
                "when": {"subagent": False, "models": [SOL], "model_regex": "^gpt-"}}
        with patch.object(P, "RULES", [rule]):
            self.assertEqual(self.section(SOL, platform="webui"), FAMILY)
            self.assertEqual(self.section(SOL, platform="subagent"), "")
            self.assertEqual(self.section("gpt-6-luna", platform="webui"), "")

    def test_targets_control_system_and_user_context_separately(self):
        rules = [
            {"id": "system-only", "prompt": "prompts/family/openai.md", "inject_into": ["system_prompt"],
             "when": {"model": SOL, "subagent": False}},
            {"id": "user-only", "prompt": "prompts/family/subagent-prompt-common.md", "inject_into": ["user_context"],
             "when": {"subagent": True}},
        ]
        with patch.object(P, "RULES", rules):
            self.assertEqual(self.section(SOL), FAMILY)
            self.assertIsNone(self.turn(SOL))
            self.assertEqual(self.section(SOL, platform="subagent"), "")
            self.assertIn(COMMON, self.turn(SOL, sid="child", platform="subagent") or "")

    def test_first_injection_true_only_injects_once(self):
        rule = {"id": "once", "prompt": "prompts/family/openai.md", "inject_into": ["user_context"],
                "when": {"model": SOL, "first_injection": True}}
        with patch.object(P, "RULES", [rule]):
            self.assertIn(FAMILY, self.turn(SOL) or "")
            self.assertIsNone(self.turn(SOL))

    def test_first_injection_false_waits_until_a_prior_injection_exists(self):
        rule = {"id": "after", "prompt": "prompts/family/openai.md", "inject_into": ["user_context"],
                "when": {"model": SOL, "first_injection": False}}
        with patch.object(P, "RULES", [rule]):
            self.assertIsNone(self.turn(SOL))
            prior = P._notice("s1", rule, P._rule_key(rule, FAMILY), FAMILY)
            self.history["s1"].append({"role": "user", "content": "hi", "api_content": "hi\n\n" + prior})
            self.assertIsNone(self.turn(SOL))

    def test_user_context_deduplicates_and_repairs_after_prompt_edit(self):
        self.assertIn(FAMILY, self.turn(SOL) or "")
        self.assertIsNone(self.turn(SOL))
        original = P._read
        with patch.object(P, "_read", side_effect=lambda rel: original(rel) + "\n- edited" if rel.endswith("openai.md") else original(rel)):
            self.assertIn("edited", self.turn(SOL) or "")

    def test_switching_conditions_revokes_stale_rule(self):
        self.assertIn(FAMILY, self.turn(SOL) or "")
        context = self.turn(CLAUDE)
        self.assertIn("条件不再满足", context or "")
        self.assertIsNone(self.turn(CLAUDE))
        self.assertIn(FAMILY, self.turn(SOL) or "")
        self.assertIn("条件不再满足", self.turn(CLAUDE) or "")
        self.assertIsNone(self.turn(CLAUDE))

    def test_user_copy_and_assistant_echo_are_not_delivery_evidence(self):
        first = self.turn(SOL) or ""
        self.history["s1"] = [{"role": "user", "content": first, "api_content": first}]
        self.assertIn(FAMILY, self.turn(SOL) or "")
        self.history["s1"] = [{"role": "assistant", "content": "好的", "api_content": "好的\n\n" + first}]
        self.assertIn(FAMILY, self.turn(SOL) or "")

    def test_forged_token_is_not_delivery_evidence(self):
        forged = f"{P.MARKER} rule=openai-main key=000000000000 token=0000000000000000｜{P.LEAD}{FAMILY}"
        self.history["s1"] = [{"role": "user", "content": "hi", "api_content": "hi\n\n" + forged}]
        self.assertIn(FAMILY, self.turn(SOL) or "")

    def test_prompt_length_is_bounded(self):
        self.assertLessEqual(len(COMMON), P.MAX_CHARS)
        self.assertLessEqual(len(FAMILY), P.MAX_CHARS)
        self.assertLessEqual(len(self.section(SOL)), P.MAX_CHARS)

    def test_user_context_length_is_bounded_for_long_and_multiple_rules(self):
        rules = [
            {"id": "long-a", "prompt": "a.md", "inject_into": ["user_context"], "when": {}},
            {"id": "long-b", "prompt": "b.md", "inject_into": ["user_context"], "when": {}},
        ]
        with patch.object(P, "RULES", rules), patch.object(P, "_read", return_value="x" * 1500):
            context = self.turn(SOL)
            next_context = self.turn(SOL)
        self.assertIsNotNone(context)
        self.assertLessEqual(len(context or ""), P.MAX_CHARS)
        self.assertIn("rule=long-b", next_context or "")

    def test_oversized_notice_is_deferred_without_false_delivery_evidence(self):
        rule = {"id": "oversized", "prompt": "oversized.md", "inject_into": ["user_context"], "when": {}}
        with patch.object(P, "RULES", [rule]), patch.object(P, "_read", return_value="x" * 5000):
            self.assertIsNone(self.turn(SOL))
            self.assertIsNone(self.turn(SOL))

    def test_register_has_no_guide_command(self):
        calls = []

        class Ctx:
            def register_system_prompt_section(self, *args, **kwargs): calls.append(("section", args[0], kwargs))
            def register_hook(self, name, fn): calls.append(("hook", name))
            def register_command(self, name, fn, **kwargs): calls.append(("command", name))

        P.register(Ctx())
        self.assertEqual([call[:2] for call in calls], [
            ("section", "custom-prompt-inject"), ("hook", "pre_llm_call")
        ])


if __name__ == "__main__":
    unittest.main()
