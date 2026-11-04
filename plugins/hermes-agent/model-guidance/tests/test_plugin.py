"""model-guidance 的离线契约检查。

判定读「宿主追加区域」里的令牌，所以 `turn` 按宿主真实载体写历史：
`api_content = 用户 content + 追加区`。用户自己写的 content 不参与判定。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN_DIR = Path(__file__).resolve().parents[1]
CHILD = """
import importlib.util, sys
from pathlib import Path
plugin_dir, state_path = sys.argv[1:3]
spec = importlib.util.spec_from_file_location("mg_child", plugin_dir + "/__init__.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["mg_child"] = mod
spec.loader.exec_module(mod)
mod._state_path = lambda: Path(state_path)
if sys.argv[3] == "loop":  # loop <prefix> <count>：连续写多个会话
    for i in range(int(sys.argv[5])):
        mod._command("daily", session_id=f"{sys.argv[4]}{i}")
else:  # one <args> <sid>
    mod._command(sys.argv[4], session_id=sys.argv[5])
"""


def load_plugin():
    spec = importlib.util.spec_from_file_location("model_guidance_under_test", PLUGIN_DIR / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


P = load_plugin()
SOL, FLASH, CLAUDE = "gpt-6.1-sol", "deepseek-flash", "claude-opus-5-5"
FAMILY = P._read("prompts/family/openai.md")
WORKER = P._read("prompts/family/worker.md")
DEEPSEEK = "prompts/family/deepseek.md"
LONG = P._read("prompts/mode/long.md")
DAILY = P._read("prompts/mode/daily.md")


def split_notice(api_content: str) -> str:
    return api_content.split("hi\n\n", 1)[1]


class TestPlugin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(P, "_state_path", lambda: Path(self.tmp.name) / "state.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        setattr(P, "_secret_cache", None)  # 每个用例用独立临时目录，密钥必须重新生成
        self.addCleanup(setattr, P, "_secret_cache", None)
        self.history: dict[str, list[dict]] = {}

    def section(self, model, sid="s1", platform="webui"):
        return P._section({"session_id": sid, "model": model, "platform": platform})

    def turn(self, model, sid="s1", platform="webui"):
        """跑一轮；按宿主真实载体落历史（content + 追加区）。"""
        hist = self.history.setdefault(sid, [])
        out = P._pre_llm_call(session_id=sid, model=model, platform=platform, conversation_history=hist)
        ctx = (out or {}).get("context")
        if ctx:
            hist.append({"role": "user", "content": "hi", "api_content": "hi\n\n" + ctx})
        return ctx

    # --- 渲染 ---

    def test_section_renders_by_model_and_mode(self):
        self.assertEqual(self.section(SOL), FAMILY + "\n\n" + LONG)
        self.assertEqual(self.section("gpt-6-luna", sid="s2"), FAMILY + "\n\n" + DAILY)
        self.assertEqual(self.section(CLAUDE, sid="s3"), "")

    def test_section_render_alone_does_not_count_as_delivered(self):
        """宿主可能因共享预算跳过 section，渲染过不等于投递过。"""
        self.assertEqual(self.section(SOL), FAMILY + "\n\n" + LONG)
        self.assertIn(LONG, self.turn(SOL))
        self.assertIsNone(self.turn(SOL))

    # --- 首轮与稳定态 ---

    def test_first_turn_injects_once_then_dedups(self):
        ctx = self.turn(SOL)
        self.assertIn(P.LEAD, ctx)
        self.assertIn(" token=", ctx)
        self.assertIsNone(self.turn(SOL))
        self.assertIsNone(self.turn(SOL))

    def test_non_openai_session_never_injects(self):
        self.assertIsNone(self.turn(CLAUDE))
        self.assertIsNone(self.turn(CLAUDE))

    def test_subagent_gets_worker_block_and_ignores_mode(self):
        self.assertEqual(self.section(SOL, sid="c1", platform="subagent"), WORKER)
        self.assertIn(WORKER, self.turn(SOL, sid="c1", platform="subagent"))
        self.assertIsNone(self.turn(SOL, sid="c1", platform="subagent"))
        # 每个族共用同一份子代理执行纪律，deepseek 子代理也拿得到
        self.assertEqual(self.section(FLASH, sid="c2", platform="subagent"), WORKER)

    def test_model_group_prompt_is_family_scoped(self):
        """模型组级固定提示词：命中 deepseek 族就注入该族正文，不叠模式块。"""
        self.assertEqual(P.resolve(FLASH, "webui", "g1"), ("deepseek", "main", ""))
        content = "## 模型组规则（DeepSeek 系）\n- 一段固定提示词"
        original = P._read
        with patch.object(P, "_read", side_effect=lambda rel: content if rel == DEEPSEEK else original(rel)):
            self.assertEqual(self.section(FLASH, sid="g1"), content)
            self.assertIn(content, self.turn(FLASH, sid="g1"))
            self.assertIsNone(self.turn(FLASH, sid="g1"))
            # 只作用于本组：未命中规则、别的族都不受影响
            self.assertEqual(self.section(CLAUDE, sid="g1"), "")
            self.assertEqual(self.section(SOL, sid="g1"), FAMILY + "\n\n" + LONG)

    def test_empty_group_prompt_injects_nothing(self):
        """正文还没写时不要往 system prompt 里塞空块。"""
        if P._read(DEEPSEEK):
            self.skipTest("deepseek.md 已有正文")
        self.assertEqual(self.section(FLASH, sid="g2"), "")
        self.assertIsNone(self.turn(FLASH, sid="g2"))

    # --- 证据必须来自宿主追加区 ---

    def test_user_authored_copy_of_notice_is_not_evidence(self):
        """用户自己贴一份（含真令牌）也不算已投递：证据只认宿主追加区。"""
        self.turn(SOL)
        real = split_notice(self.history["s1"][0]["api_content"])
        self.history["s1"] = [{"role": "user", "content": real, "api_content": real}]
        self.assertIn(LONG, self.turn(SOL))

    def test_forged_token_is_not_evidence(self):
        forged = f"{P.MARKER} key=openai|main|long token=0123456789abcdef｜{P.LEAD}{LONG}"
        self.history["s1"] = [{"role": "user", "content": "hi", "api_content": "hi\n\n" + forged}]
        self.assertIn(LONG, self.turn(SOL))

    def test_multimodal_text_part_is_not_evidence(self):
        """多模态的 text part 与用户自己的 part 无法区分，一律不作证据：宁可多注入一次。"""
        ctx = self.turn(SOL)
        self.history["s1"] = [{"role": "user", "content": [{"type": "text", "text": "看图"},
                                                           {"type": "text", "text": ctx}]}]
        self.assertIn(LONG, self.turn(SOL))

    def test_assistant_sidecar_is_not_evidence(self):
        """宿主也会给 assistant 行写 api_content；模型复述注入内容不能被当成规则仍在。"""
        ctx = self.turn(SOL)
        self.history["s1"] = [{"role": "assistant", "content": "好的", "api_content": "好的\n\n" + ctx}]
        self.assertIn(LONG, self.turn(SOL))

    def test_platform_preamble_does_not_break_dedup(self):
        """真实消息里 content 在中间（平台会在前面加工作区标记与 memory-context），仍要去重。"""
        ctx = self.turn(SOL)
        api = "[Workspace::v1: /repo]\n问一句\n\n<memory-context>回忆</memory-context>\n\n" + ctx
        self.history["s1"] = [{"role": "user", "content": "问一句", "api_content": api}]
        self.assertIsNone(self.turn(SOL))

    def test_missing_content_falls_back_to_full_scan(self):
        """定位不到 content 时退化为整段扫描（偏保守：宁可多注入，也不漏撤规则）。"""
        ctx = self.turn(SOL)
        self.history["s1"] = [{"role": "user", "content": "对不上的正文", "api_content": "原始正文\n\n" + ctx}]
        self.assertIsNone(self.turn(SOL))

    def test_secret_loss_still_sends_off_notice(self):
        """secret 重建使旧令牌失效时，切 off 仍要补一次停用声明。"""
        self.turn(SOL)
        P._command("off", session_id="s1")
        Path(self.tmp.name, "secret").unlink()   # 模拟密钥丢失/重建
        setattr(P, "_secret_cache", None)
        self.assertIn("已不适用", self.turn(SOL))

    def test_secret_created_once_across_processes(self):
        """两个进程同时首次初始化，必须收敛到同一份 canonical secret。"""
        state = Path(self.tmp.name) / "state.json"
        code = (
            "import importlib.util,sys;from pathlib import Path;"
            "s=importlib.util.spec_from_file_location('mg',sys.argv[1]+'/__init__.py');"
            "m=importlib.util.module_from_spec(s);sys.modules['mg']=m;s.loader.exec_module(m);"
            "m._state_path=lambda: Path(sys.argv[2]);"
            "print(m._token('sid','k'))"
        )
        outs = [subprocess.run([sys.executable, "-I", "-c", code, str(PLUGIN_DIR), str(state)],
                               capture_output=True, text=True, timeout=60).stdout.strip()
                for _ in range(2)]
        self.assertTrue(all(outs) and outs[0] == outs[1], outs)

    def test_replayed_turn_without_new_carrier_self_heals(self):
        """/retry 之类重放旧历史的轮次：本轮没有当前 key 的载体，下一轮必须补。"""
        self.turn(SOL)
        P._command("daily", session_id="s1")
        self.assertIn(DAILY, self.turn(SOL))
        self.history["s1"] = self.history["s1"][:1]  # 模拟重放把 daily 那轮丢掉
        self.assertIn(DAILY, self.turn(SOL))

    # --- 模型 / 模式切换 ---

    def test_switch_model_injects_once(self):
        self.turn(CLAUDE)
        ctx = self.turn(SOL)
        self.assertIn("取代系统提示里的 model-guidance", ctx)
        self.assertIn(LONG, ctx)
        self.assertIsNone(self.turn(SOL))
        self.assertIn("已不适用", self.turn(CLAUDE))
        self.assertIsNone(self.turn(CLAUDE))

    def test_session_command_overrides_only_that_session(self):
        self.turn(SOL)
        self.turn(SOL, sid="other")
        self.assertIn("本会话", P._command("daily", session_id="s1"))
        ctx = self.turn(SOL)
        self.assertIn(DAILY, ctx)
        self.assertNotIn(LONG, ctx)
        self.assertIsNone(self.turn(SOL, sid="other"))
        self.assertIn("本会话: daily", P._command("status", session_id="s1"))
        P._command("off", session_id="s1")
        self.assertIn("已不适用", self.turn(SOL))
        P._command("auto", session_id="s1")
        self.assertIn(LONG, self.turn(SOL))
        self.assertIsNone(self.turn(SOL))

    def test_global_command_below_session_setting(self):
        self.turn(SOL)
        self.turn(SOL, sid="pinned")
        P._command("long", session_id="pinned")
        self.assertIn("全局默认", P._command("global daily", session_id="s1"))
        self.assertIn(DAILY, self.turn(SOL))
        self.assertIsNone(self.turn(SOL, sid="pinned"))
        self.assertIn("全局默认", P._command("auto"))
        self.assertIn(LONG, self.turn(SOL))
        for bad in ("bogus", "global bogus", "daily extra"):
            self.assertIn("用法", P._command(bad, session_id="s1"))
        self.assertIn("全局默认: 按模型", P._command("global", session_id="s1"))

    def test_command_receives_session_via_host_dispatch(self):
        from hermes_cli.plugin_command_dispatch import invoke_plugin_command
        invoke_plugin_command(P._command, "daily", source="webui", platform="webui", session_id="s9")
        self.assertIn("本会话: daily", P._command("status", session_id="s9"))

    # --- hook 不写状态、不持锁 ---

    def test_hook_does_not_write_state_or_take_lock(self):
        """hook 在宿主超时名单里：这条路径上不能有状态写，也不能有 flock。"""
        with patch.object(P, "_locked_state", side_effect=AssertionError("hook 路径不得加锁")):
            self.assertIn(LONG, self.turn(SOL))
        self.assertFalse((Path(self.tmp.name) / "state.json").exists(), "hook 不该写状态")

    def test_prompt_edit_takes_effect_without_restart(self):
        self.assertFalse(hasattr(P._read, "cache_info"))
        original = P._read
        v2 = LONG + "\n- v2"
        with patch.object(P, "_read", side_effect=lambda rel: v2 if rel.endswith("long.md") else original(rel)):
            self.assertIn("v2", self.section(SOL, sid="fresh"))

    def test_state_survives_corrupt_file(self):
        (Path(self.tmp.name) / "state.json").write_text("{not json", encoding="utf-8")
        self.assertIn("本会话: 跟随默认", P._command("status", session_id="s1"))
        self.assertIn("本会话模式已设为 daily", P._command("daily", session_id="s1"))

    # --- 跨进程（只针对 /guide 写路径）---

    def test_concurrent_processes_do_not_lose_writes(self):
        """两个进程各连写 40 个会话；无跨进程锁时实测稳定丢 35/80，有锁时 0 丢失。"""
        state = Path(self.tmp.name) / "state.json"
        count = 40
        procs = [subprocess.Popen([sys.executable, "-I", "-c", CHILD, str(PLUGIN_DIR), str(state), "loop", prefix, str(count)])
                 for prefix in ("a", "b")]
        for p in procs:
            self.assertEqual(p.wait(timeout=120), 0, "子进程写入失败")
        sessions = json.loads(state.read_text(encoding="utf-8"))["sessions"]
        for prefix in ("a", "b"):
            for i in range(count):
                self.assertEqual(sessions.get(f"{prefix}{i}"), {"mode": "daily"}, f"{prefix}{i} 被覆盖")

    def test_concurrent_global_and_session_writes_both_survive(self):
        """冒烟用例：命中率受调度影响，稳定回归是上面那条批量写。"""
        state = Path(self.tmp.name) / "state.json"
        p1 = subprocess.Popen([sys.executable, "-I", "-c", CHILD, str(PLUGIN_DIR), str(state), "one", "global off", ""])
        p2 = subprocess.Popen([sys.executable, "-I", "-c", CHILD, str(PLUGIN_DIR), str(state), "one", "daily", "sess"])
        self.assertEqual(p1.wait(timeout=60), 0)
        self.assertEqual(p2.wait(timeout=60), 0)
        data = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(data.get("global_mode"), "off")
        self.assertEqual((data.get("sessions") or {}).get("sess"), {"mode": "daily"})

    # --- 预算与注册 ---

    def test_budget(self):
        for mode in ("long", "daily"):
            self.assertLessEqual(len(FAMILY) + 2 + len(P._read(f"prompts/mode/{mode}.md")), P.MAX_CHARS)
            self.assertLessEqual(len(P._read(DEEPSEEK)) + 2 + len(P._read(f"prompts/mode/{mode}.md")), P.MAX_CHARS)
        self.assertLessEqual(len(WORKER), P.MAX_CHARS)

    def test_register(self):
        calls = []

        class Ctx:
            def register_system_prompt_section(self, *a, **k): calls.append(("section", a[0], k))
            def register_hook(self, name, fn): calls.append(("hook", name))
            def register_command(self, name, fn, **k): calls.append(("command", name))

        P.register(Ctx())
        self.assertEqual([c[:2] for c in calls],
                         [("section", "model-guidance"), ("hook", "pre_llm_call"), ("command", "guide")])


if __name__ == "__main__":
    unittest.main()
