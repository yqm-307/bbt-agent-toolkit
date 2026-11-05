"""omh-dag-boundary 的离线契约检查：只测 pre_tool_call 的改写结果，不依赖宿主。"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dag_boundary", PLUGIN_DIR / "__init__.py")
assert spec and spec.loader
P = importlib.util.module_from_spec(spec)
sys.modules["dag_boundary"] = P
spec.loader.exec_module(P)

DAG_GOAL = "实现 X [dag:run-1/node-a]"


def hook(args, tool="delegate_task"):
    return P._pre_tool_call(tool_name=tool, args=args, task_id="t", session_id="s")


def merged(args, directive):
    """宿主对 modify 的处理：把 args 浅合并进原参数。"""
    return {**args, **directive["args"]}


class DagBoundary(unittest.TestCase):
    def test_single_dag_task_gets_clause_on_context(self):
        args = {"goal": DAG_GOAL, "context": "TASK: a", "role": "leaf"}
        out = merged(args, hook(args))
        self.assertEqual(out["context"], "TASK: a" + P.CLAUSE)
        self.assertEqual((out["goal"], out["role"]), (DAG_GOAL, "leaf"))

    def test_single_dag_task_without_context(self):
        out = merged({"goal": DAG_GOAL}, hook({"goal": DAG_GOAL}))
        self.assertEqual(out["context"], P.CLAUSE)

    def test_non_dag_and_other_tools_are_left_alone(self):
        self.assertIsNone(hook({"goal": "review x", "context": "TASK: y"}))
        self.assertIsNone(hook({"goal": DAG_GOAL, "context": "c"}, tool="terminal"))
        self.assertIsNone(hook("not a dict"))
        self.assertIsNone(hook(None))

    def test_marker_must_be_in_goal_and_well_formed(self):
        self.assertIsNone(hook({"goal": "x", "context": "see [dag:run-1/node-a]"}))
        for bad in ("[dag:]", "[dag:run]", "[dag:/n]", "dag:run/node", "[dag: run/node]"):
            self.assertIsNone(hook({"goal": f"x {bad}", "context": "c"}), bad)
        self.assertIsNotNone(hook({"goal": "x [dag:repo-hygiene/fw-p3a-repair]", "context": "c"}))

    def test_marker_must_sit_at_either_end_and_use_omh_charset(self):
        """真实派发里标记既可能在结尾也可能在开头；只认首尾，中间引用不算。"""
        for bad in ("普通路径 [dag:r/a/b]",                       # 多一个斜杠
                    "普通审查：解释正则例子 [dag:r/n]，无需 DAG",   # 在中间
                    "x [dag:r/n] extra",                         # 后面还有别的字
                    "[dag:r/n][]",                               # 首部标记后面不是空白
                    "x [dag:r n]",                               # 空格
                    "x [dag:[r]/n]",                             # 嵌套左括号
                    "x [dag:运行/节点]",                          # 中文不是合法 ID
                    "x [dag:r_/n]",                              # 下划线
                    "x [dag:R/N]",                               # 大写
                    "x [dag:-r/n]",                              # 连字符开头
                    "x [dag:" + "a" * 33 + "/n]",                # 超过 32 字符
                    "x [dag:r/n"):
            self.assertIsNone(hook({"goal": bad, "context": "c"}), bad)
        for good in ("x [dag:r/n]   ",                        # 尾部标记 + 尾随空白
                     "[dag:demo-run/node-a]",                 # 只有标记
                     "[dag:demo-run/prepare] 标签"):          # 首部标记 + 标签
            self.assertIsNotNone(hook({"goal": good, "context": "c"}), good)

    def test_non_string_goal_is_left_alone(self):
        for goal in ({"a": 1}, ["[dag:r/n]"], 7, None):
            self.assertIsNone(hook({"goal": goal, "context": "c"}), repr(goal))
            self.assertIsNone(hook({"tasks": [{"goal": goal, "context": "c"}]}), repr(goal))

    def test_batch_only_dag_tasks_change_and_order_is_kept(self):
        tasks = [{"goal": "a [dag:r/a]", "context": "TASK: a"}, {"goal": "plain", "context": "TASK: b"},
                 {"goal": "c [dag:r/c]"}]
        args = {"tasks": tasks}
        out = merged(args, hook(args))["tasks"]
        self.assertEqual([t["goal"] for t in out], [t["goal"] for t in tasks])
        self.assertEqual(out[0]["context"], "TASK: a" + P.CLAUSE)
        self.assertEqual(out[1], tasks[1])
        self.assertEqual(out[2]["context"], P.CLAUSE)

    def test_batch_ignores_top_level_context(self):
        args = {"context": "shared", "tasks": [{"goal": "a [dag:r/a]"}]}
        out = merged(args, hook(args))
        self.assertEqual(out["context"], "shared")  # 宿主不读它，也不该把条款写进去
        self.assertEqual(out["tasks"][0]["context"], P.CLAUSE)

    def test_tasks_as_json_string(self):
        args = {"tasks": json.dumps([{"goal": "a [dag:r/a]", "context": "TASK: a"}])}
        out = merged(args, hook(args))["tasks"]
        self.assertEqual(out[0]["context"], "TASK: a" + P.CLAUSE)
        self.assertIsNone(hook({"tasks": "{not json"}))

    def test_idempotent_and_input_untouched(self):
        for args in ({"goal": DAG_GOAL, "context": "c"}, {"tasks": [{"goal": "a [dag:r/a]", "context": "c"}]}):
            before = copy.deepcopy(args)
            directive = hook(args)
            self.assertEqual(args, before)
            self.assertIsNone(hook(merged(args, directive)))

    def test_clause_names_the_three_actions_and_defers_to_not_do(self):
        for word in ("VERIFY", "Git", "SCOPE", "范围外请求", "NOT DO", "交接文件除外"):
            self.assertIn(word, P.CLAUSE)

    def test_logging_failure_does_not_escape(self):
        """宿主把 hook 抛出的异常当成 block：日志失败也必须返回 None。"""
        calls = []
        original = P._needs_clause

        def boom(task):
            raise RuntimeError("business path failed")

        class Bad:
            def warning(self, *a, **k):
                calls.append(1)
                raise OSError("log sink down")

        P._needs_clause = boom
        P.logger = Bad()
        try:
            self.assertIsNone(hook({"goal": DAG_GOAL, "context": "c"}))
        finally:
            P._needs_clause = original
        self.assertEqual(len(calls), 1)  # 真的走到了日志，而且没逃出去

    def test_register_wires_pre_tool_call(self):
        calls = []

        class Ctx:
            def register_hook(self, name, fn):
                calls.append((name, fn))

        P.register(Ctx())
        self.assertEqual(calls, [("pre_tool_call", P._pre_tool_call)])


if __name__ == "__main__":
    unittest.main()
