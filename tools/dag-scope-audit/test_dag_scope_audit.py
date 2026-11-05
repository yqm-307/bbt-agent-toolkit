#!/usr/bin/env python3
"""Regression for dag_scope_audit: python3 -m unittest discover -s tools/dag-scope-audit -p 'test_*.py'"""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dag_scope_audit as A  # noqa: E402

REPO = "/w/repo"


class Classify(unittest.TestCase):
    def kinds(self, cmd):
        return [k for k, _ in A.classify(cmd)]

    def test_runner_behind_cd_wrappers_and_pipe(self):
        self.assertEqual(self.kinds("cd build && JOBS=4 timeout 600 ctest -R net --output-on-failure | tail -5"), ["test"])

    def test_listing_is_not_a_run(self):
        self.assertEqual(self.kinds("ctest -N | head"), [])

    def test_build_and_test_targets(self):
        self.assertEqual(self.kinds("make -C build -j2 CMakeFiles/x.dir/a.o"), ["build"])
        self.assertEqual(self.kinds("make -j2 test"), ["test"])

    def test_git_reads_vs_side_effects(self):
        self.assertEqual(self.kinds("git stash list && git diff"), [])
        self.assertEqual(self.kinds("git -C repo stash"), ["git"])
        self.assertEqual(self.kinds("git reset -q && git restore --staged x"), [])
        self.assertEqual(self.kinds("git reset --hard HEAD"), ["git"])

    def test_index_config_and_worktree_writes(self):
        cmd = "git add -A && git config user.name x && git update-index --assume-unchanged f && git worktree add ../w"
        self.assertEqual(self.kinds(cmd), ["git"] * 4)
        self.assertEqual(self.kinds("git config --get user.name && git worktree list && git add -N new.cc"), [])
        self.assertEqual(self.kinds("git merge-tree a b && git merge-base a b"), [])

    def test_patch_check_is_read_only(self):
        self.assertEqual(self.kinds("git apply --check --reverse fix.patch"), [])

    def test_heredoc_body_and_text_are_skipped(self):
        self.assertEqual(self.kinds("python3 - <<'EOF'\nimport os; os.system('ctest')\nEOF\nrg ctest docs"), [])


class Allowances(unittest.TestCase):
    def test_verify_names_a_test(self):
        a = A.allowances("TASK: x\nVERIFY: 跑 ctest -R net，不跑全量\nSTOP WHEN: done")
        self.assertTrue(a["test"] and a["build"])

    def test_not_do_forbids(self):
        a = A.allowances("TASK: x\nVERIFY: 静态核对接口\nSTOP WHEN: done\nNOT DO: 不跑测试或构建，不重构")
        self.assertFalse(a["test"] or a["build"] or a["git_verbs"])
        self.assertTrue(a["test_forbidden"] and a["build_forbidden"])

    def test_not_do_beats_check_role_default(self):
        a = A.allowances("TASK: 核对\nVERIFY: 读代码\nSTOP WHEN: done\nNOT DO: 不跑测试", "verify")
        self.assertFalse(a["test"])
        self.assertTrue(a["build"])

    def test_build_role_compiles_by_default(self):
        self.assertTrue(A.allowances("TASK: 实现\nVERIFY: 交付可编译产物\nSTOP WHEN: done")["build"])

    def test_no_verify_section_asks_for_no_tests(self):
        a = A.allowances("TASK: 给测试框架加一个 helper\nSTOP WHEN: done")
        self.assertTrue(a["no_verify"])
        self.assertFalse(a["test"])

    def test_git_nouns_are_not_requests(self):
        self.assertEqual(A.allowances("TASK: 基于 base commit SHA 和 feature branch 改代码\nVERIFY: 交付")["git_verbs"], [])
        self.assertEqual(A.allowances("TASK: 改完后提交并推送\nVERIFY: 交付")["git_verbs"], ["add", "commit", "push"])

    def test_section_after_chinese_punctuation(self):
        self.assertEqual(A.sections("改完不提交。VERIFY: 跑 ctest -R a")["VERIFY"].strip(), "跑 ctest -R a")

    def test_claim_wording_is_not_a_prohibition(self):
        a = A.allowances("TASK: x\nVERIFY: 实际执行候选命令，不声称全量测试通过\nSTOP WHEN: done")
        self.assertTrue(a["test"])
        self.assertFalse(a["test_forbidden"])
        self.assertFalse(A.allowances("TASK: 修 x，不改测试\nVERIFY: 交付\nSTOP WHEN: done")["test_forbidden"])

    def test_gap_between_negation_and_action(self):
        self.assertTrue(A.allowances("TASK: x\nVERIFY: 交付\nSTOP WHEN: done\n不要去跑测试")["test_forbidden"])

    def test_scope_limits_are_not_bans(self):
        a = A.allowances("TASK: x\nVERIFY: 交付\nSTOP WHEN: done\n不重新跑全部构建，不构建无必要目标\nNOT DO: 完整测试套件")
        self.assertFalse(a["build_forbidden"] or a["test_forbidden"])

    def test_git_prohibition_names_the_verb(self):
        self.assertEqual(A.allowances("TASK: x，不commit/push\nVERIFY: 交付\nSTOP WHEN: done")["git_verbs_forbidden"],
                         ["commit", "push"])
        self.assertEqual(A.allowances("TASK: x\nVERIFY: 交付\nSTOP WHEN: done\nNOT DO: git 写操作")["git_verbs_forbidden"], ["*"])

    def test_silent_prompt_is_unrequested_not_forbidden(self):
        a = A.allowances("TASK: 实现 Foo\nVERIFY: 交付代码\nSTOP WHEN: done")
        self.assertFalse(a["test"] or a["test_forbidden"])


class Paths(unittest.TestCase):
    def test_relative_path_against_absolute_scope(self):
        self.assertTrue(A.in_scope("src/a/x.cc", [f"{REPO}/src/a/"]))
        self.assertTrue(A.in_scope("./src/a/x.cc", ["src/a/"]))
        self.assertFalse(A.in_scope("x.cc", [f"{REPO}/src/a/"]))

    def test_written_paths_keep_any_extension_and_only_skip_runtime_roots(self):
        calls = [("write_file", {"path": f"{REPO}/src/handoff_parser.py"}), ("write_file", {"path": f"{REPO}/web/a.css"}),
                 ("write_file", {"path": f"{REPO}/src/out/x.py"}), ("write_file", {"path": "/tmp/x.log"}),
                 ("write_file", {"path": "/o/runtime/dag/s/r/n.md"})]
        A.ROOTS = [Path("/o/runtime"), Path("/h/cache/scratch")]
        try:
            self.assertEqual(A.written_paths(calls), [f"{REPO}/src/handoff_parser.py", f"{REPO}/web/a.css",
                                                      f"{REPO}/src/out/x.py"])
        finally:
            A.ROOTS = []


def node(nid, prompt, scope, role="build", origin="define"):
    return {"id": nid, "label": nid, "role": role, "prompt": prompt, "write_scope": scope, "depends_on": [], "origin": origin}


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.omh = root / "omh"
        run_dir = self.omh / "runtime" / "dag" / "sess"
        (run_dir / "r1").mkdir(parents=True)
        record = {"run": "r1", "defined_at": 1.0, "nodes": [
            node("impl", "TASK: 实现\nVERIFY: 交付代码\nSTOP WHEN: done\nNOT DO: 不跑测试", [f"{REPO}/src/a/"]),
            node("core", "TASK: 实现\nVERIFY: 跑 ctest -R core\nSTOP WHEN: done", [f"{REPO}/CMakeLists.txt"]),
            node("review", "TASK: 审查\nVERIFY: 读代码\nSTOP WHEN: done", [], role="review"),
            node("fix-core", "TASK: 修\nVERIFY: 交付\nSTOP WHEN: done", [], role=None, origin="repair:core"),
            node("verify-a", "TASK: 验\nVERIFY: 每项有证据\nSTOP WHEN: done", [], role=None),
            node("verify-b", "TASK: 验\nVERIFY: 每项有证据\nSTOP WHEN: done", [f"{REPO}/src/a/"], role="verify"),
        ]}
        (run_dir / "r1.json").write_text(json.dumps(record), encoding="utf-8")
        self.db = root / "state.db"
        con = sqlite3.connect(self.db)
        con.execute("create table sessions (id text, source text, started_at real)")
        con.execute("create table messages (id integer primary key, session_id text, role text, content text, tool_calls text)")

        def child(sid, nid, calls):
            con.execute("insert into sessions values (?, 'subagent', 10.0)", (sid,))
            con.execute("insert into messages (session_id, role, content) values (?, 'user', ?)", (sid, f"x [dag:r1/{nid}]"))
            tc = [{"id": str(i), "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(calls)]
            con.execute("insert into messages (session_id, role, tool_calls) values (?, 'assistant', ?)", (sid, json.dumps(tc)))

        child("s-impl", "impl", [("patch", {"path": f"{REPO}/src/a/a.cc"}),
                                 ("write_file", {"path": f"{REPO}/CMakeLists.txt"}),
                                 ("write_file", {"path": f"{REPO}/docs/x.md"}),
                                 ("patch", {"path": "CMakeLists.txt"}),
                                 ("terminal", {"command": "cmake --build build && ctest -R a"})])
        child("s-core", "core", [("write_file", {"path": f"{REPO}/CMakeLists.txt"}),
                                 ("terminal", {"command": "cmake --build build && ctest -R core"})])
        child("s-review", "review", [("patch", {"path": f"{REPO}/src/a/a.cc"})])
        child("s-fix", "fix-core", [("write_file", {"path": f"{REPO}/CMakeLists.txt"})])
        child("s-verify", "verify-a", [("terminal", {"command": "ctest"}), ("write_file", {"path": f"{REPO}/src/a/b.cc"})])
        child("s-verify-b", "verify-b", [("patch", {"path": f"{REPO}/src/a/c.cc"})])
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def findings(self, results, nid):
        return sorted(f["kind"] for r in results if r["node"] == nid for f in r["findings"])

    def test_findings_per_node(self):
        res = A.audit(self.db, self.omh, 0.0, "r1")
        self.assertEqual(self.findings(res, "impl"),
                         ["foreign_scope_write", "foreign_scope_write", "out_of_scope_write", "prohibited_test"])
        self.assertEqual(self.findings(res, "core"), [])
        self.assertEqual(self.findings(res, "review"), ["check_role_write"])
        self.assertEqual(self.findings(res, "fix-core"), [])
        verify_a = next(r for r in res if r["node"] == "verify-a")
        self.assertEqual((verify_a["role"], verify_a["role_source"]), ("verify", "legacy_label"))
        self.assertFalse(verify_a["allow"]["test"])  # a guessed role never grants the check-role defaults
        self.assertEqual(self.findings(res, "verify-a"), ["foreign_scope_write", "unrequested_test"])
        # verify is never a producer in OMH, so its own declared scope does not license work-file writes
        self.assertEqual(self.findings(res, "verify-b"), ["check_role_write"])
        owner = [f for r in res for f in r["findings"] if f["kind"] == "foreign_scope_write"][0]["owner"]
        self.assertEqual(owner, "core")

    def test_summary_rates(self):
        s = A.summarize(A.audit(self.db, self.omh, 0.0))
        self.assertEqual((s["children"], s["build_children"]), (6, 3))
        self.assertEqual(s["build"]["any"], "1/3")


if __name__ == "__main__":
    unittest.main()
