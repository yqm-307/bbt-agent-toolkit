"""extract_inventory.py 的离线测试：切分、标记、引用、近似重复、--follow 与 CLI。"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import extract_inventory as ei  # noqa: E402

DOC = """---
name: demo
---
# 规则

## 授权

- 必须先获用户授权才能提交。
- 如果用户已授权，可直接开 PR。
- 非 trivial 变更先出方案；有疑问先问。

| 场景 | 做法 |
|---|---|
| 新依赖 | 先确认 |

```bash
cmake --build build --parallel "$JOBS"
```

详见 `docs/exists.md` 与 `docs/missing.md`，分支 `feat/x` 不算路径，占位 `<dir>/a.md` 跳过，裸名 `run.py` 不报缺失。
拿不准就先问；路径写绝对路径。
参考 [指南](docs/exists.md#节) 和 https://example.com/guide 。
"""


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "exists.md").write_text("# 被引用\n\n必须先获用户授权才能提交代码。\n", encoding="utf-8")
        self.target = self.root / "AGENTS.md"
        self.target.write_text(DOC, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def inv(self, follow=False, threshold=0.5):
        return ei.build_inventory([self.target], self.root, follow, threshold)

    def unit(self, inv, needle):
        return next(u for u in inv["units"] if needle in u["text"])

    def test_blocks_kinds_and_heading_path(self):
        inv = self.inv()
        kinds = {u["kind"] for u in inv["units"]}
        self.assertTrue({"frontmatter", "list", "table", "code", "para"} <= kinds)
        self.assertEqual(self.unit(inv, "必须先获")["heading"], "规则 > 授权")
        self.assertEqual(self.unit(inv, "新依赖")["kind"], "table")
        code = self.unit(inv, "cmake --build")
        self.assertEqual((code["kind"], code["flags"]), ("code", []))

    def test_sentence_split_gives_stable_ids(self):
        inv = self.inv()
        first = self.unit(inv, "非 trivial")
        second = self.unit(inv, "有疑问先问")
        self.assertEqual(first["line"], second["line"])
        self.assertTrue(first["id"].endswith(".1") and second["id"].endswith(".2"))

    def test_flags(self):
        inv = self.inv()
        self.assertIn("unscoped_absolute", self.unit(inv, "必须先获")["flags"])
        scoped = self.unit(inv, "如果用户已授权")["flags"]
        self.assertIn("gate", scoped)
        self.assertNotIn("unscoped_absolute", scoped)
        self.assertIn("vague", self.unit(inv, "非 trivial")["flags"])
        self.assertIn("gate", self.unit(inv, "有疑问先问")["flags"])
        # 「拿不准」「绝对路径」不是绝对化措辞
        self.assertNotIn("absolute", self.unit(inv, "拿不准")["flags"])
        self.assertNotIn("absolute", self.unit(inv, "绝对路径")["flags"])

    def test_references(self):
        refs = {r["target"]: r["status"] for r in self.inv()["references"]}
        self.assertEqual(refs["docs/exists.md"], "ok")
        self.assertEqual(refs["docs/missing.md"], "missing")
        self.assertEqual(refs["docs/exists.md#节"], "ok")
        self.assertEqual(refs["https://example.com/guide"], "url")
        self.assertNotIn("feat/x", refs)
        self.assertNotIn("<dir>/a.md", refs)
        self.assertNotIn("run.py", refs)

    def test_large_inventory_note(self):
        big = self.root / "big.md"
        big.write_text("\n\n".join(f"第 {k} 条规则写在这里。" for k in range(ei.LARGE_INVENTORY + 1)), encoding="utf-8")
        inv = ei.build_inventory([big], self.root, False, 0.99)
        self.assertTrue(any("--follow" in note for note in inv["summary"]["notes"]))

    def test_follow_adds_referenced_markdown_and_finds_cross_file_duplicate(self):
        plain = self.inv()
        self.assertEqual(len(plain["files"]), 1)
        inv = self.inv(follow=True)
        self.assertEqual([f["followed"] for f in inv["files"]], [False, True])
        pairs = {(p["a"].split("-")[0], p["b"].split("-")[0]) for p in inv["near_duplicates"]}
        self.assertIn(("F1", "F2"), pairs)

    def test_short_sentences_not_compared(self):
        units = [{"id": "a", "kind": "para", "text": "先确认"}, {"id": "b", "kind": "para", "text": "先确认"}]
        self.assertEqual(ei.near_duplicates(units, 0.5)[0], [])

    def test_cli_markdown_and_missing_file(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = ei.main([str(self.target), "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("## 机械检查摘要", out.getvalue())
        self.assertIn("`F1-L", out.getvalue())
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(ei.main([str(self.root / "nope.md")]), 2)

    def test_flagged_only_drops_unflagged(self):
        md = ei.render_md(self.inv(), flagged_only=True)
        self.assertIn("必须先获", md)
        self.assertNotIn("cmake --build", md)

    def test_verify_findings(self):
        inv = self.inv()
        good = self.unit(inv, "必须先获")["id"]
        lines = [
            json.dumps({"lane": "B", "ids": [good], "quote": "必须先获…才能提交"}, ensure_ascii=False),
            json.dumps({"lane": "B", "ids": ["F1-L999.1"], "quote": "必须先获"}, ensure_ascii=False),
            json.dumps({"lane": "B", "ids": [good], "quote": "原文里没有这句"}, ensure_ascii=False),
            '{"lane": "A", "none": true}',
            "{broken",
            json.dumps({"lane": "B", "id": [good], "quote": "必须先获"}, ensure_ascii=False),
            "- 列表形式的发现",
            json.dumps({"lane": "B", "ids": [good], "quote": None}),
        ]
        total, problems = ei.verify_findings(inv, lines)
        self.assertEqual(total, 3)
        self.assertEqual([p["line"] for p in problems], [2, 3, 5, 6, 7, 8])
        self.assertEqual(len(ei.verify_findings(inv, [])[1]), 1)
        self.assertEqual(ei.verify_findings(inv, ['{"lane": "C", "none": true}']), (0, []))
        findings = self.root / "findings.jsonl"
        findings.write_text(lines[0] + "\n", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ei.main([str(self.target), "--root", str(self.root), "--verify", str(findings)]), 0)

    def test_cli_json_out(self):
        dest = self.root / "out" / "inv.json"
        with redirect_stdout(io.StringIO()):
            ei.main([str(self.target), "--root", str(self.root), "--format", "json", "--out", str(dest)])
        data = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(data["summary"]["missing_refs"], 1)
        self.assertEqual(self.target.read_text(encoding="utf-8"), DOC)


if __name__ == "__main__":
    unittest.main()
