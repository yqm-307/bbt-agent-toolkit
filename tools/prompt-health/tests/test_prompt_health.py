"""prompt_health.py 的重名回归：相同 frontmatter 名称必须报 REF-DUPLICATE ERROR。

契约来源：tools/prompt-health/DESIGN.md —— skill 名称重复为 ERROR；
--gate 在错误或警告存在时返回 1；发现项需包含重复双方路径。

夹具为「相同 frontmatter 名称、不同正文、不同目录」的两个 SKILL.md：
正文互不相同，因此 DUPLICATE-CONTENT（内容哈希告警）不可能触发，
失败原因只能指向重名检查本身。每个文件各带一个不同的缺失依赖，
防止「只报重名、dict 覆盖仍隐藏其中一份的 REF-MISSING」的部分修复蒙混过关。

夹具放在仓外临时目录并通过 setUp 断言其不在任何 Git 工作树内，
经真实 CLI（subprocess）观察退出值与输出，避免 tracked-only 过滤。

运行（无统一测试命令，按组件目录直接执行）：
    python3 -m unittest discover -s tools/prompt-health/tests -v
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "prompt_health.py"

SKILL_NAME = "dupe-target"

# 路径 → 文件全文；正文与 description 互不相同，related_skills 各指向一个不存在的 skill。
FIXTURES = {
    "skills/handbooks/SKILL.md": (
        "---\n"
        "name: dupe-target\n"
        'description: "First copy, wired to its own missing dependency."\n'
        "related_skills: [missing-one]\n"
        "---\n"
        "First body talks about exit codes and logs.\n"
    ),
    "skills/reports/SKILL.md": (
        "---\n"
        "name: dupe-target\n"
        'description: "Second copy, wired to another missing dependency."\n'
        "related_skills: [missing-two]\n"
        "---\n"
        "Second body talks about checklists and summaries.\n"
    ),
}

# 文件 → （自身的缺失依赖名）；用于绑定「这一份文件的具体错误被单独报告」。
MISSING_DEPS = {
    "skills/handbooks/SKILL.md": "missing-one",
    "skills/reports/SKILL.md": "missing-two",
}


class DuplicateSkillNameGateTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="prompt-health-dupname-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for rel, text in FIXTURES.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        probe = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(
            probe.returncode, 0,
            f"夹具目录落在 Git 工作树内，未跟踪文件会被 tracked-only 过滤：{self.root}")

    def test_duplicate_skill_name_is_error_and_gate_fails(self):
        proc = subprocess.run(
            [sys.executable, str(TOOL), "--root", str(self.root), "--gate"],
            capture_output=True, text=True)
        out = proc.stdout
        detail = f"（rc={proc.returncode}）gate 输出：\n{out}{proc.stderr}"
        # 夹具正文互不相同：任何命中都必须来自重名/引用检查，而不是内容哈希告警。
        self.assertNotIn("DUPLICATE-CONTENT", out, f"内容告警不应触发{detail}")
        dup_lines = [ln for ln in out.splitlines() if f"REF-DUPLICATE-{SKILL_NAME}" in ln]
        self.assertTrue(dup_lines, f"重名 skill 未报 REF-DUPLICATE ERROR{detail}")
        self.assertEqual(len(dup_lines), 1, f"重名发现行不唯一：\n" + "\n".join(dup_lines))
        for rel in FIXTURES:
            self.assertIn(rel, dup_lines[0], f"重名发现未包含双方路径{detail}")
        # 两个同名文件各自的缺失依赖都要可见：按名称覆盖会让其中一份的具体错误消失。
        for rel, dep in MISSING_DEPS.items():
            lines = [ln for ln in out.splitlines()
                     if f"REF-MISSING-{SKILL_NAME}-{dep}" in ln]
            self.assertTrue(
                lines and rel in lines[0],
                f"{rel} 的缺失依赖 {dep} 未随该文件单独报告{detail}")
        self.assertEqual(proc.returncode, 1, f"--gate 应在重名 ERROR 存在时退出 1{detail}")


if __name__ == "__main__":
    unittest.main()
