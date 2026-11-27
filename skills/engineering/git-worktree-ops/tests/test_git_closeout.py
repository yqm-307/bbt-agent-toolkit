"""git_closeout.py 的回归：真实 git 仓库 + 本地裸远端 + gh 替身，走真实 CLI 观察结果。

覆盖：ship 全链路（推送、开 PR、等 CI、合并、快进基线、清理）、无 CI、CI 失败、
分支保护拦截、脏工作区拦截，以及 census 的判读；另覆盖审查指出的阻塞路径：
其他基线的旧 PR 不复用、清理只删仍停在已合并 head 的对象、CI 异常输出都停下、
基线/主分支不走收口、gh -R 只钉 github.com。

运行（在本 skill 目录）：
    python3 -B -m unittest discover -s tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "scripts" / "git_closeout.py"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True,
                          capture_output=True, text=True).stdout.strip()


class CloseoutCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(f"#!/bin/sh\nexec {sys.executable} {HERE / 'gh_stub.py'} \"$@\"\n")
        (bindir / "gh").chmod(0o755)
        self.state = self.tmp / "gh-state.json"
        self.state.write_text(json.dumps({"prs": []}))
        self.env = {**GIT_ENV, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_STUB_STATE": str(self.state)}
        self.remote = self.tmp / "remote.git"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.main = self.tmp / "repo"
        git(self.tmp, "clone", "-q", str(self.remote), str(self.main))
        (self.main / "a.txt").write_text("a\n")
        git(self.main, "add", "a.txt")
        git(self.main, "commit", "-q", "-m", "init")
        git(self.main, "push", "-q", "-u", "origin", "main")
        git(self.main, "remote", "set-head", "origin", "main")
        self.wt = self.tmp / "wt-feat"
        git(self.main, "worktree", "add", "-q", "-b", "feat/x", str(self.wt), "origin/main")
        (self.wt / "b.txt").write_text("b\n")
        git(self.wt, "add", "b.txt")
        git(self.wt, "commit", "-q", "-m", "feat: add b")
        self.head = git(self.wt, "rev-parse", "HEAD")

    def gh_state(self, **updates):
        state = json.loads(self.state.read_text())
        state.update(updates)
        self.state.write_text(json.dumps(state))
        return state

    def cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(TOOL), *args], cwd=cwd or self.wt, env=self.env,
                              capture_output=True, text=True)

    def ship(self, *extra):
        return self.cli("ship", "--no-ci-grace", "0", "--interval", "0", *extra)

    def remote_ref(self, branch):
        out = git(self.main, "ls-remote", "origin", f"refs/heads/{branch}")
        return out.split("\t")[0] if out else None

    def hook(self, *commands):
        """登记 pr merge 后执行的命令；命令必须 touch self.tmp/adv-sha，用例据此发现静默失败。"""
        marker = self.tmp / "adv-sha"
        marker.unlink(missing_ok=True)
        self.gh_state(post_merge=[c + f" && touch {marker}" for c in commands])
        return marker

    def branch_exists(self, branch):
        return subprocess.run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
                              cwd=self.main, env=self.env, capture_output=True).returncode == 0

    def test_ship_full_chain(self):
        proc = self.ship()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["ci"], "pass")
        self.assertEqual(result["merge_commit"], self.head)
        self.assertEqual(result["url"], "https://example.invalid/pull/1")
        self.assertEqual(self.remote_ref("main"), self.head)
        self.assertEqual(git(self.main, "rev-parse", "main"), self.head, "本地基线应快进")
        self.assertFalse(self.wt.exists(), "worktree 应被删除")
        self.assertEqual(git(self.main, "branch", "--list", "feat/x"), "")
        self.assertIsNone(self.remote_ref("feat/x"))

    def test_ship_without_ci_merges_and_says_so(self):
        self.gh_state(checks="none")
        proc = self.ship()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["ci"], "none")
        self.assertEqual(self.remote_ref("main"), self.head)

    def test_ci_failure_stops_before_merge(self):
        self.gh_state(checks="fail")
        proc = self.ship()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("CI 失败", proc.stderr)
        self.assertNotEqual(self.remote_ref("main"), self.head)
        self.assertTrue(self.wt.exists())

    def test_branch_protection_stops_before_merge(self):
        self.gh_state(merge_state="BLOCKED")
        proc = self.ship()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("BLOCKED", proc.stderr)
        self.assertNotEqual(self.remote_ref("main"), self.head)
        calls = json.loads(self.state.read_text())["calls"]
        self.assertFalse(any(c[:2] == ["pr", "merge"] for c in calls))

    def test_no_merge_stops_after_ci(self):
        proc = self.ship("--no-merge")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("stopped", json.loads(proc.stdout))
        self.assertNotEqual(self.remote_ref("main"), self.head)
        self.assertEqual(self.remote_ref("feat/x"), self.head)

    def test_dirty_worktree_stops_before_push(self):
        (self.wt / "c.txt").write_text("c\n")
        proc = self.ship()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("未提交改动", proc.stderr)
        self.assertIsNone(self.remote_ref("feat/x"))

    # ---------- sync：基线安全快进 ----------

    def advance_remote_main(self):
        """在另一个克隆里向远端 main 推一个提交，本地 main 因此落后。"""
        other = self.tmp / "advancer"
        git(self.tmp, "clone", "-q", str(self.remote), str(other))
        (other / "a.txt").write_text("a\nremote addition\n")
        git(other, "add", "a.txt")
        git(other, "commit", "-q", "-m", "advance main")
        git(other, "push", "-q", "origin", "main")
        return git(other, "rev-parse", "HEAD")

    def sync(self, *extra, cwd=None):
        return self.cli("sync", *extra, cwd=cwd or self.main)

    def test_sync_fastforwards_clean_baseline(self):
        remote_head = self.advance_remote_main()
        proc = self.sync()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertIn("快进", result["action"])
        self.assertEqual(git(self.main, "rev-parse", "main"), remote_head)

    def test_sync_noop_when_up_to_date(self):
        proc = self.sync()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("一致", json.loads(proc.stdout)["action"])

    def test_sync_stops_on_dirty_baseline(self):
        self.advance_remote_main()
        (self.main / "dirty.txt").write_text("dirty\n")
        proc = self.sync()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("未提交改动", proc.stderr)
        self.assertNotEqual(git(self.main, "rev-parse", "main"), self.remote_ref("main"))

    def test_sync_stops_on_unpushed_local_commits(self):
        self.advance_remote_main()
        (self.main / "local.txt").write_text("local\n")
        git(self.main, "add", "local.txt")
        git(self.main, "commit", "-q", "-m", "local only")
        proc = self.sync()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("未推送提交", proc.stderr)

    def test_sync_overlay_dirty_fastforwards_and_drops_stash(self):
        """未提交改动正好是远端新增内容的覆盖：stash 证明后快进，改动随快进消除。"""
        remote_head = self.advance_remote_main()
        # 覆盖语义是：diff HEAD 等于远端相对 HEAD 的变化。直接复制远端那笔提交的净变化（远端改的是 a.txt）
        git(self.main, "fetch", "-q", "origin", "main")
        patch = subprocess.run(["git", "diff", "--binary", "HEAD", "origin/main"],
                               cwd=self.main, env=self.env, capture_output=True, text=True,
                               check=True).stdout
        subprocess.run(["git", "apply"], cwd=self.main, env=self.env, input=patch,
                       capture_output=True, text=True, check=True)
        proc = self.sync()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertIn("覆盖", result["action"])
        self.assertEqual(git(self.main, "rev-parse", "main"), remote_head)
        self.assertEqual(git(self.main, "stash", "list"), "")
        self.assertEqual(git(self.main, "status", "--porcelain"), "")

    def test_sync_dirty_non_overlay_stops(self):
        """未提交改动与远端无关：不证明，不快进。"""
        self.advance_remote_main()
        (self.main / "a.txt").write_text("modified locally\n")
        proc = self.sync()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("未提交改动", proc.stderr)
        self.assertEqual((self.main / "a.txt").read_text(), "modified locally\n")

    def test_census_reads_worktree_and_merged_branch(self):
        (self.wt / "c.txt").write_text("c\n")
        git(self.main, "branch", "old/merged", "main")
        proc = self.cli("census", "--json", str(self.main), cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        items = {i["branch"]: i["state"] for i in json.loads(proc.stdout)[0]["items"]}
        self.assertEqual(items["main"], "与远端一致")
        self.assertIn("进行中", items["feat/x"])
        self.assertEqual(items["old/merged"], "已合并，可删除")

    # ---------- A1：其他基线的旧 PR ----------

    def test_A1_ship_does_not_reuse_old_pr_merged_into_other_base(self):
        """A1：同 head 的旧 PR 合入的是 release，ship --base main 必须新开指向 main 的 PR。"""
        git(self.main, "push", "-q", "origin", "main:refs/heads/release")
        self.gh_state(prs=[{"number": 1, "url": "https://example.invalid/pull/1", "state": "MERGED",
                            "headRefName": "feat/x", "headRefOid": self.head, "baseRefName": "release",
                            "isDraft": False, "mergeStateStatus": "CLEAN",
                            "mergeCommit": {"oid": self.head}}])
        proc = self.ship("--base", "main")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["pr"], 2, "应新开指向 main 的 PR，而不是复用 #1")
        self.assertEqual(self.remote_ref("main"), self.head)
        self.assertEqual(self.remote_ref("release"), git(self.main, "rev-parse", "main~1"),
                         "release 基线不应被动到")

    def test_A1_census_not_mark_squash_merged_into_other_base(self):
        """A1：分支只是 squash 合入了 release，census 对 main 基线不得报「已合并，可删除」。"""
        git(self.main, "branch", "side", self.head)
        self.gh_state(prs=[{"number": 1, "url": "https://example.invalid/pull/1", "state": "MERGED",
                            "headRefName": "side", "headRefOid": self.head, "baseRefName": "release",
                            "isDraft": False, "mergeStateStatus": "CLEAN", "mergeCommit": None}])
        proc = self.cli("census", "--json", str(self.main), cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        items = {i["branch"]: i["state"] for i in json.loads(proc.stdout)[0]["items"]}
        self.assertEqual(items["side"], "未合并")

    def test_A1b_pr_rebased_to_other_base_during_wait_stops(self):
        """A1b：等 CI 期间 PR 被改投到 release → 合并前 Stop，退出码 2，不调用 pr merge。"""
        self.gh_state(steal_base="release")
        proc = self.ship()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("等待期间变了", proc.stderr)
        calls = json.loads(self.state.read_text())["calls"]
        self.assertFalse(any(c[:2] == ["pr", "merge"] for c in calls))
        self.assertNotEqual(self.remote_ref("main"), self.head, "不应合入 main")

    # ---------- A2：清理只删仍停在已合并 head 的对象 ----------

    def test_A2_cleanup_keeps_worktree_switched_away_during_wait(self):
        """A2：等 CI 期间 worktree 已切到别的提交（detached），合并后不得删除该 worktree。"""
        marker = self.hook(f"git -C {self.wt} checkout -q --detach HEAD~1")
        proc = self.ship()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(marker.exists(), "钩子静默失败")
        notes = json.loads(proc.stdout)["cleanup"]
        self.assertTrue(self.wt.exists(), "切走的 worktree 不应被删除")
        self.assertTrue(any("已不在" in n for n in notes), notes)

    def test_A2_remote_advanced_keeps_remote_only(self):
        """A2：远端分支被推进 → 删 worktree 和本地分支，保留远端分支。"""
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", str(self.remote), str(other))
        marker = self.hook(
            f"sh -c 'cd {other} && git fetch -q origin feat/x && git checkout -q -B adv origin/feat/x"
            f" && echo z > z.txt && git add z.txt && git commit -q -m later"
            f" && git push -q origin adv:refs/heads/feat/x && git rev-parse HEAD > {self.tmp}/adv.txt'")
        proc = self.ship()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(marker.exists(), "钩子静默失败")
        advanced = (self.tmp / "adv.txt").read_text().strip()
        self.assertEqual(self.remote_ref("feat/x"), advanced, "被推进的远端分支不应删除")
        self.assertFalse(self.wt.exists(), "仍停在已合并 head 的 worktree 应删除")
        self.assertFalse(self.branch_exists("feat/x"), "未推进的本地分支应删除")

    def test_A2_local_advanced_keeps_local_branch_and_worktree(self):
        """A2：本地分支被推进到新提交 → worktree 与本地分支都保留，远端分支正常删除。"""
        # 本地造一个新提交（不动远端），把 feat/x 推进过去
        marker = self.hook(
            f"sh -c 'new=$(git -C {self.main} commit-tree"
            f" $(git -C {self.main} rev-parse HEAD^{{tree}})"
            f" -p $(git -C {self.main} rev-parse HEAD) -m later)"
            f" && git -C {self.main} update-ref refs/heads/feat/x $new"
            f" && echo $new > {self.tmp}/adv.txt'")
        proc = self.ship()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(marker.exists(), "钩子静默失败")
        advanced = (self.tmp / "adv.txt").read_text().strip()
        self.assertTrue(self.wt.exists(), "不再停在已合并 head 的 worktree 不应删除")
        self.assertEqual(git(self.main, "rev-parse", "feat/x"), advanced, "被推进的本地分支不应删除")
        # cleanup 在 worktree 已不在时提前返回，远端分支也不会被删
        self.assertEqual(self.remote_ref("feat/x"), self.head, "远端分支不应被动到")
        notes = json.loads(proc.stdout)["cleanup"]
        self.assertTrue(any("未清理" in n for n in notes), notes)

    def test_A2_cleanup_removes_branch_config(self):
        """A2：正常路径删除本地分支后不留 branch.<name>.* 配置。"""
        proc = self.ship()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        config = git(self.main, "config", "--list", "--local")
        self.assertFalse([l for l in config.splitlines() if l.startswith("branch.feat/x.")],
                         config)

    # ---------- A3：CI 读数的异常都要停下 ----------

    def test_A3_checks_pending_then_vanish_never_says_none(self):
        """A3：先见到 pending、之后变成 no checks → 不得返回 ci=none，应等到超时 Stop。"""
        self.gh_state(checks=["pending", "none"])
        proc = self.ship("--timeout", "0")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("仍未结束", proc.stderr)
        self.assertNotEqual(self.remote_ref("main"), self.head, "不应合并")

    def test_A3_malformed_checks_output_stops(self):
        """A3：检查输出里有不足 3 个 tab 分隔列的行 → Stop，不合并。"""
        self.gh_state(checks="malformed")
        proc = self.ship("--timeout", "10")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("读不懂", proc.stderr)
        self.assertNotEqual(self.remote_ref("main"), self.head)

    def test_A3_all_pass_with_nonzero_exit_code_stops(self):
        """A3：检查全部 pass 但 gh 退出码非 0 → Stop，不合并。"""
        self.gh_state(checks="pass", checks_exit=3)
        proc = self.ship()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("退出码", proc.stderr)
        self.assertNotEqual(self.remote_ref("main"), self.head)

    def test_A3_vanishing_named_check_keeps_waiting(self):
        """A3b：首轮 build=pass、test=pending，次轮只剩 build=pass 且退出 0 → 不得返回 pass，超时 Stop。"""
        self.gh_state(checks_rounds=[[["build", "pass"], ["test", "pending"]],
                                     [["build", "pass"]]])
        # timeout 给 1s、interval 0：首轮 test=pending 不停，走到第二轮只剩 build=pass 也不得判 pass
        proc = self.ship("--timeout", "1")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("仍未结束", proc.stderr)
        self.assertNotEqual(self.remote_ref("main"), self.head, "不应合并")

    # ---------- A4：基线与主分支不走收口 ----------

    def test_A4_ship_from_main_worktree_with_other_base_stops(self):
        """A4：linked worktree 里检出 main 并 ship --base release → 退出码 2 且不推送。"""
        git(self.main, "push", "-q", "origin", "main:refs/heads/release")
        git(self.main, "checkout", "-q", "--detach")
        wt_main = self.tmp / "wt-main"
        git(self.main, "worktree", "add", "-q", str(wt_main), "main")
        proc = self.cli("ship", "--base", "release", "--no-ci-grace", "0", "--interval", "0", cwd=wt_main)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("不走收口", proc.stderr)
        calls = json.loads(self.state.read_text()).get("calls", [])
        self.assertFalse(any(c[:2] == ["pr", "create"] for c in calls), "不应开 PR")
        self.assertIsNone(self.remote_ref("feat/x"), "分支不应被推送")

    def test_A4_census_never_lists_master_or_base(self):
        """A4：census 不把 master / 基线列为可清理对象。"""
        git(self.main, "branch", "master", "main")
        git(self.main, "push", "-q", "origin", "main:refs/heads/release")
        proc = self.cli("census", "--json", str(self.main), cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)[0]
        self.assertEqual(report["base"], "main")
        branches = [i["branch"] for i in report["items"]]
        self.assertNotIn("master", branches)
        self.assertNotIn("release", branches)

    def test_A4_ship_uses_remote_default_branch_not_local_origin_head(self):
        """A4b：远端 HEAD 改指 trunk、本地 origin/HEAD 仍指 main → 在 trunk 上 ship 退出码 2，不推送。"""
        git(self.main, "push", "-q", "origin", "main:refs/heads/trunk")
        trunk_sha = self.remote_ref("trunk")
        subprocess.run(["git", "--git-dir", str(self.remote), "symbolic-ref", "HEAD",
                        "refs/heads/trunk"], check=True, capture_output=True)
        wt_trunk = self.tmp / "wt-trunk"
        git(self.main, "worktree", "add", "-q", "-b", "trunk", str(wt_trunk), "origin/main")
        (wt_trunk / "t.txt").write_text("t\n")  # 本地 trunk 领先远端：ship 若误走流程会推进远端 trunk
        git(wt_trunk, "add", "t.txt")
        git(wt_trunk, "commit", "-q", "-m", "trunk work")
        proc = self.cli("ship", "--base", "main", "--no-ci-grace", "0", "--interval", "0", cwd=wt_trunk)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("不走收口", proc.stderr)
        self.assertEqual(self.remote_ref("trunk"), trunk_sha, "ship 不应推送 trunk")


class GhCmdCase(unittest.TestCase):
    """gh_cmd 只有 origin 主机恰好是 github.com 时才加 -R。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = self.tmp / "r"
        git(self.tmp, "init", "-q", str(self.repo))

    def gh_args(self, url):
        git(self.repo, "remote", "add", "origin", url)
        sys.path.insert(0, str(HERE.parent / "scripts"))
        import git_closeout
        return git_closeout.gh_cmd(self.repo)

    def test_github_urls_get_dash_r(self):
        for url in ("git@github.com:o/r", "ssh://git@github.com/o/r", "https://github.com/o/r",
                    "https://user@github.com/o/r", "https://github.com/o/r.git"):
            self.assertEqual(self.gh_args(url), ["gh", "-R", "o/r"], url)
            subprocess.run(["git", "remote", "remove", "origin"], cwd=self.repo,
                           env=GIT_ENV, check=True, capture_output=True)

    def test_non_github_host_gets_no_dash_r(self):
        self.assertEqual(self.gh_args("git@mirror-github.com:o/r"), ["gh"])


if __name__ == "__main__":
    unittest.main()
