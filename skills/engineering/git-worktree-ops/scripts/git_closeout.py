#!/usr/bin/env python3
"""git-closeout：盘点仓库收尾状态（census），安全快进本地基线（sync），把一个分支走完 PR 收口（ship），批量清理已合并对象（clean）。

census 只读（--fetch 时只更新远端跟踪引用）。sync 快进本地基线：干净则 ff，未提交改动经覆盖证明
才 stash 快进，其余情况停下。ship 依次推送、开或复用 PR、等 CI、合并、快进本地基线、清理 worktree
与分支；每一步回读真实状态，条件不满足就停下并说明原因。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SHA_RE = re.compile(r"[0-9a-f]{40}")
MERGEABLE_STATES = {"CLEAN", "HAS_HOOKS", "UNSTABLE"}


class Stop(Exception):
    """收口条件不满足：带原因停下，不执行后续步骤。"""


def run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    except FileNotFoundError:
        raise Stop(f"找不到命令 {args[0]}") from None
    if check and proc.returncode != 0:
        raise Stop(f"`{' '.join(args)}` 失败：{(proc.stderr or proc.stdout).strip()}")
    return proc


def git(cwd: Path, *args: str, check: bool = True) -> str:
    return run(["git", *args], cwd, check).stdout.strip()


def sha_of(cwd: Path, rev: str) -> str:
    out = git(cwd, "rev-parse", "--verify", f"{rev}^{{commit}}")
    if not SHA_RE.fullmatch(out):
        raise Stop(f"`{rev}` 解析出的不是提交 SHA：{out!r}")
    return out


def gh_cmd(cwd: Path, *args: str) -> list[str]:
    """origin 在 GitHub 上时用 -R 钉住它，不让 gh 按其他 remote 或 set-default 推断目标仓。"""
    url = git(cwd, "remote", "get-url", "origin", check=False)
    m = re.match(r"(?:https://(?:[^@/]+@)?|ssh://git@|git@)github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return ["gh", *args, *(["-R", m.group(1)] if m else [])]


def gh_json(cwd: Path, *args: str) -> Any:
    """读失败（鉴权、网络、命令不存在）和输出损坏都 Stop，不当成「没有记录」。"""
    proc = run(gh_cmd(cwd, *args), cwd)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise Stop(f"`gh {' '.join(args)}` 输出不是 JSON：{proc.stdout[:200]!r}") from None


def list_prs(cwd: Path, branch: str, base: str, state: str, fields: str) -> list[dict]:
    """同仓、从 branch 指向 base 的 PR（新的在前）；fork 同名分支和指向其他基线的 PR 不算。"""
    prs = gh_json(cwd, "pr", "list", "--head", branch, "--base", base, "--state", state,
                  "--json", f"{fields},baseRefName,isCrossRepository")
    return [pr for pr in prs if pr["baseRefName"] == base and not pr["isCrossRepository"]]


def default_base(repo: Path) -> str:
    ref = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    return ref.split("/", 1)[1] if ref.startswith("origin/") else "main"


def remote_default(repo: Path) -> str | None:
    """远端 HEAD 当前指向的分支（本地 origin/HEAD 可能缺失或过期）；读不到返回 None。"""
    out = git(repo, "ls-remote", "--symref", "origin", "HEAD", check=False)
    m = re.match(r"ref: refs/heads/(\S+)\tHEAD", out)
    return m.group(1) if m else None


def long_lived(repo: Path, base: str, remote: bool = False) -> set[str]:
    """不能当功能分支推送、也不能被清理的分支；remote=True 时另问远端当前的默认分支。"""
    names = {base, default_base(repo), "main", "master"}
    if remote and (name := remote_default(repo)):
        names.add(name)
    return names


def worktrees(repo: Path) -> list[dict]:
    """`git worktree list --porcelain` 的条目；第一条是主工作区。"""
    items, cur = [], {}
    for line in git(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line:
            if cur:
                items.append(cur)
            cur = {}
            continue
        key, _, value = line.partition(" ")
        cur[key] = value or True
    for item in items:
        item["path"] = Path(item["worktree"])
        ref = item.get("branch")
        item["branch"] = ref.removeprefix("refs/heads/") if isinstance(ref, str) else None
    return items


def dirty_count(path: Path) -> int:
    return len(git(path, "status", "--porcelain").splitlines())


def merged_into(repo: Path, rev: str, base: str, branch: str | None, use_gh: bool) -> bool:
    """rev 是否已进入基线：祖先关系直接判定；squash 合并只能靠指向同一基线的 PR 记录（需要 gh）。"""
    if run(["git", "merge-base", "--is-ancestor", rev, f"origin/{base}"], repo, check=False).returncode == 0:
        return True
    if not (use_gh and branch):
        return False
    try:
        prs = list_prs(repo, branch, base, "merged", "headRefOid")
    except Stop:
        return False  # gh 读不到时按未合并报，宁可漏报可清理
    return any(pr["headRefOid"] == rev for pr in prs)


# ---------- census ----------

def repos_under(root: Path) -> list[Path]:
    """根目录下（含根目录自身）的主仓：`.git` 是目录才算，是文件的是 linked worktree，由其主仓的
    census 覆盖，不单列；找到主仓不再往其内部下探，目录不可读跳过，符号链接不跟随（防环）。

    深度上限：根目录自身算第 0 层，向下探到第 4 层为止——主仓通常在代码根下一两层，4 层封顶避免整盘扫描。
    """
    found: list[Path] = []

    def walk(dir_: Path, depth: int) -> None:
        try:
            with os.scandir(dir_) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            return
        if (dir_ / ".git").is_dir():
            found.append(dir_)
            return
        if depth >= 4:
            return
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                walk(Path(entry.path), depth + 1)

    walk(root, 0)
    return found


def census_repo(repo: Path, fetch: bool, use_gh: bool) -> dict:
    repo = Path(git(repo, "rev-parse", "--show-toplevel"))
    fetch_error = None
    if fetch:
        proc = run(["git", "fetch", "--prune", "-q", "origin"], repo, check=False)
        fetch_error = proc.stderr.strip() or "fetch 失败" if proc.returncode else None
    base = default_base(repo)
    base_ref = f"origin/{base}"
    has_base = run(["git", "rev-parse", "--verify", "-q", base_ref], repo, check=False).returncode == 0
    rows, seen, keep = [], set(), long_lived(repo, base, remote=fetch)
    for i, wt in enumerate(worktrees(repo)):
        branch, path = wt["branch"], wt["path"]
        seen.add(branch)
        row = {"kind": "main" if i == 0 else "worktree", "path": str(path), "branch": branch}
        if "prunable" in wt or not path.is_dir():
            row["state"] = "登记失效（prunable），确认目录后再 git worktree prune"
            rows.append(row)
            continue
        row["head"] = wt.get("HEAD", "")
        row["dirty"] = dirty_count(path)
        if not has_base:
            row["state"] = f"找不到 {base_ref}，无法比较"
        elif branch == base:
            ahead = int(git(path, "rev-list", "--count", f"{base_ref}..HEAD"))
            behind = int(git(path, "rev-list", "--count", f"HEAD..{base_ref}"))
            row.update(ahead=ahead, behind=behind)
            if ahead:
                row["state"] = f"基线有 {ahead} 个未推送提交"
            elif behind:
                row["state"] = f"落后 {behind}，" + ("可快进" if not row["dirty"] else "有未提交改动，先处理再快进")
            else:
                row["state"] = "与远端一致"
        else:
            head = wt.get("HEAD", "")
            ahead = int(git(path, "rev-list", "--count", f"{base_ref}..HEAD"))
            row["ahead"] = ahead
            if row["dirty"]:
                row["state"] = "有未提交改动，进行中"
            elif branch in keep:
                row["state"] = f"长期分支，{ahead} 个提交不在 {base_ref}，不清理"
            elif ahead == 0:
                row["state"] = "没有独有提交且干净，删除不丢内容"
            elif merged_into(repo, head, base, branch, use_gh):
                row["state"] = "已合并且干净，可清理"
            else:
                row["state"] = f"{ahead} 个提交未合并，进行中"
        if row["dirty"] and "未提交" not in row["state"]:
            row["state"] += f"；另有 {row['dirty']} 个未提交改动"
        rows.append(row)
    if has_base:
        for branch in git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines():
            if branch in seen or branch in keep:
                continue
            head = sha_of(repo, branch)
            merged = merged_into(repo, head, base, branch, use_gh)
            rows.append({"kind": "branch", "path": "", "branch": branch, "head": head,
                         "state": "已合并，可删除" if merged else "未合并"})
    return {"repo": str(repo), "base": base, "fetch_error": fetch_error, "items": rows}


def print_census(reports: list[dict]) -> None:
    for rep in reports:
        print(f"## {rep['repo']}（基线 {rep['base']}）")
        if rep["fetch_error"]:
            print(f"- fetch 失败，以下按本地已有的远端引用判读：{rep['fetch_error']}")
        for row in rep["items"]:
            where = f"  {row['path']}" if row["kind"] == "worktree" else ""
            print(f"- [{row['kind']}] {row['branch'] or '(detached)'}：{row['state']}{where}")


# ---------- sync ----------

def stash_overlay_proof(main_wt: Path, base: str) -> bool:
    """基线工作区未提交改动正好等于 origin/<base> 相对 HEAD 的内容时返回真。

    两项都成立才允许 stash 快进：HEAD 是 origin/<base> 的祖先；`git diff --binary HEAD`
    导出的补丁能在 read-tree origin/<base> 的临时索引上反向应用。
    """
    if run(["git", "merge-base", "--is-ancestor", "HEAD", f"origin/{base}"], main_wt,
           check=False).returncode:
        return False
    # 补丁不能用 git() 的 strip：末尾换行是补丁语法的一部分
    patch = run(["git", "diff", "--binary", "HEAD", "--"], main_wt).stdout
    if not patch.strip():
        return False
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if subprocess.run(["git", "read-tree", f"origin/{base}"], cwd=main_wt, env=env,
                          capture_output=True, text=True).returncode:
            return False
        proc = subprocess.run(["git", "apply", "--cached", "--reverse", "--check"],
                              cwd=main_wt, env=env, input=patch, capture_output=True, text=True)
        return proc.returncode == 0



def sync_base(repo: Path, base: str | None) -> dict:
    top = Path(git(repo, "rev-parse", "--show-toplevel"))
    base = base or remote_default(top) or default_base(top)
    git(top, "fetch", "-q", "origin", base)
    remote = sha_of(top, f"origin/{base}")
    holder = next((wt for wt in worktrees(top) if wt["branch"] == base), None)
    result = {"repo": str(top), "base": base, "remote": remote}
    if holder is None:
        proc = run(["git", "fetch", "-q", "origin", f"{base}:{base}"], top, check=False)
        if proc.returncode:
            raise Stop(f"本地 {base} 未更新：{proc.stderr.strip()}")
        result["action"] = f"本地 {base} 已更新到 {remote[:12]}（无 checkout）"
        return result
    path = holder["path"]
    head = sha_of(path, "HEAD")
    behind = int(git(path, "rev-list", "--count", f"HEAD..origin/{base}"))
    ahead = int(git(path, "rev-list", "--count", f"origin/{base}..HEAD"))
    if ahead:
        raise Stop(f"{path} 的 {base} 有 {ahead} 个未推送提交，先处理，不快进")
    if not behind:
        result["action"] = f"{base} 已与远端一致（{head[:12]}）"
        return result
    if not dirty_count(path):
        proc = run(["git", "merge", "--ff-only", "-q", f"origin/{base}"], path, check=False)
        if proc.returncode:
            raise Stop(f"{base} 无法快进：{proc.stderr.strip()}")
        result["action"] = f"{path} 的 {base} 已快进 {behind} 个提交到 {remote[:12]}"
        return result
    if not stash_overlay_proof(path, base):
        raise Stop(f"{path} 有未提交改动且不是刚合入远端内容的覆盖，先保全再同步；落后 {behind} 个提交")
    git(path, "stash", "push", "-q", "-m", "git-closeout sync overlay")
    proc = run(["git", "merge", "--ff-only", "-q", f"origin/{base}"], path, check=False)
    if proc.returncode:
        pop = run(["git", "stash", "pop", "-q"], path, check=False)
        restored = "未提交改动已还原" if pop.returncode == 0 else "改动仍在 stash 中，需手动 stash pop"
        raise Stop(f"{base} 无法快进：{proc.stderr.strip()}（{restored}）")
    git(path, "stash", "drop", "-q")
    result["action"] = (f"{path} 的 {base} 已快进 {behind} 个提交到 {remote[:12]}；"
                        "未提交改动经覆盖证明后随快进消除")
    return result


# ---------- ship ----------

def wait_checks(repo: Path, number: int, timeout: int, no_ci_grace: int, interval: int) -> str:
    """轮询 `gh pr checks` 直到全部结束。返回 "pass"，或 "none"（从开始到宽限期满一直明确报告没有检查）；
    失败、输出读不懂、退出码与状态矛盾或超时则 Stop。见过的检查（按名字）又不见了，按未结束继续等。"""
    started, seen = time.monotonic(), set()
    while True:
        proc = run(gh_cmd(repo, "pr", "checks", str(number)), repo, check=False)
        text = (proc.stdout + proc.stderr).strip()
        rows = [line.split("\t") for line in proc.stdout.splitlines() if line.strip()]
        if any(len(row) < 3 for row in rows):
            raise Stop(f"读不懂 PR #{number} 的检查输出：\n{text}")
        statuses, names = [row[1] for row in rows], {row[0] for row in rows}
        vanished, seen = seen - names, seen | names
        elapsed = time.monotonic() - started
        if not statuses:
            if "no checks reported" not in text:
                raise Stop(f"读取 PR #{number} 的检查失败：{text}")
            if not seen and elapsed >= no_ci_grace:
                return "none"
        elif any(s in ("fail", "cancel") for s in statuses):
            raise Stop(f"PR #{number} 的 CI 失败：\n{proc.stdout.strip()}")
        elif all(s in ("pass", "skipping") for s in statuses) and not vanished:
            if proc.returncode != 0:
                raise Stop(f"PR #{number} 的检查全部通过但 gh 退出码是 {proc.returncode}：\n{text}")
            return "pass"
        if elapsed >= timeout:
            raise Stop(f"PR #{number} 的 CI 等待超过 {timeout}s 仍未结束：\n{text}")
        time.sleep(interval)


def wait_mergeable(repo: Path, number: int, base: str, head: str, tries: int = 10, interval: int = 3) -> dict:
    # ponytail: `gh pr merge` 只能用 --match-head-commit 锁 head、锁不住 base；这里回读到发出合并之间
    # 若被改投，靠合并后的 baseRefName 回读兜底（发现即停，不更新基线不清理）。gh 支持锁 base 时改用它。
    info: dict = {}
    for _ in range(tries):
        info = gh_json(repo, "pr", "view", str(number), "--json",
                       "state,isDraft,mergeStateStatus,baseRefName,headRefOid")
        if (info["state"], info["baseRefName"], info["headRefOid"]) != ("OPEN", base, head):
            raise Stop(f"PR #{number} 在等待期间变了（{info['state']}，基线 {info['baseRefName']}，"
                       f"head {str(info['headRefOid'])[:12]}），不合并")
        if info["isDraft"]:
            raise Stop(f"PR #{number} 是草稿，不合并")
        if info["mergeStateStatus"] != "UNKNOWN":
            break
        time.sleep(interval)
    state = info["mergeStateStatus"]
    if state not in MERGEABLE_STATES:
        hint = {"BLOCKED": "分支保护要求未满足（如需要审批）", "BEHIND": "基线有新提交，先更新分支再收口",
                "DIRTY": "与基线冲突"}.get(state, "GitHub 不允许合并")
        raise Stop(f"PR #{number} 当前不可合并：{state}，{hint}")
    return info


def update_base(repo: Path, main_wt: Path, base: str) -> str:
    git(repo, "fetch", "-q", "origin", base)
    remote = sha_of(repo, f"origin/{base}")
    holder = next((wt for wt in worktrees(repo) if wt["branch"] == base), None)
    if holder is None:
        proc = run(["git", "fetch", "-q", "origin", f"{base}:{base}"], main_wt, check=False)
        return f"本地 {base} 已更新到 {remote[:12]}" if proc.returncode == 0 else f"本地 {base} 未更新：{proc.stderr.strip()}"
    if dirty_count(holder["path"]):
        return f"{holder['path']} 有未提交改动，未快进 {base}（远端 {remote[:12]}）"
    proc = run(["git", "merge", "--ff-only", "-q", f"origin/{base}"], holder["path"], check=False)
    if proc.returncode != 0:
        return f"{base} 无法快进：{proc.stderr.strip()}"
    return f"{holder['path']} 的 {base} 已快进到 {remote[:12]}"


def delete_branch(main_wt: Path, branch: str, head: str) -> list[str]:
    """按 OID 条件删本地分支、按 force-with-lease 删远端分支；任何一处已推进或仍被检出就保留并说明。"""
    notes = []
    if any(w["branch"] == branch for w in worktrees(main_wt)):
        notes.append(f"本地分支 {branch} 仍被其他工作区检出，未删除")
    elif run(["git", "update-ref", "-d", f"refs/heads/{branch}", head], main_wt, check=False).returncode == 0:
        run(["git", "config", "--remove-section", f"branch.{branch}"], main_wt, check=False)
        notes.append(f"已删除本地分支 {branch}")
    else:
        notes.append(f"本地分支 {branch} 已不在 {head[:12]}，未删除")
    remote = git(main_wt, "ls-remote", "origin", f"refs/heads/{branch}").split("\t")[0]
    if remote and remote != head:
        notes.append(f"远端分支 {branch} 已推进到 {remote[:12]}，未删除")
    elif remote:
        proc = run(["git", "push", "-q", f"--force-with-lease=refs/heads/{branch}:{head}",
                    "origin", f":refs/heads/{branch}"], main_wt, check=False)
        notes.append(f"已删除远端分支 {branch}" if proc.returncode == 0 else f"远端分支未删除：{proc.stderr.strip()}")
    return notes


def cleanup(main_wt: Path, top: Path, branch: str, head: str) -> list[str]:
    """只删仍停在已合并 head 上的对象；等 CI 期间任何一处变了（切走、推进、被别处检出）就保留并说明。"""
    # ponytail: git 没有「仍在 X 才删」的原子操作，回读与删除之间留有毫秒级窗口。不会丢数据：
    # worktree remove 不带 --force，有改动或未跟踪文件会拒绝；本地分支按 OID 条件删除，删掉的只是已合并的指针。
    if top == main_wt:
        return [f"分支 {branch} 检出在主工作区，未切换也未删除"]
    wt = next((w for w in worktrees(main_wt) if w["path"] == top), None)
    if wt is None or wt["branch"] != branch or wt.get("HEAD") != head:
        return [f"worktree {top} 已不在 {branch}@{head[:12]}，未清理"]
    proc = run(["git", "worktree", "remove", str(top)], main_wt, check=False)
    if proc.returncode != 0:
        return [f"worktree 未删除（不强删）：{proc.stderr.strip()}；含 submodule 时按 git-worktree-ops 第 4 节处理"]
    return [f"已删除 worktree {top}", *delete_branch(main_wt, branch, head)]


def read_pr(repo: Path, branch: str, base: str, head: str, tries: int = 10, interval: int = 2) -> dict | None:
    """回读本分支指向 base 的同仓 PR：优先打开的，其次以这个 head 合并的；打开的 PR 刚推送时可能还没
    同步到新 head，短暂重试。关闭的、合并了别的提交的旧 PR 不复用。"""
    pr = None
    for _ in range(tries):
        prs = list_prs(repo, branch, base, "all", "number,url,state,headRefOid")
        pr = (next((p for p in prs if p["state"] == "OPEN"), None)
              or next((p for p in prs if p["state"] == "MERGED" and p["headRefOid"] == head), None))
        if pr is None or pr["state"] != "OPEN" or pr["headRefOid"] == head:
            return pr
        time.sleep(interval)
    return pr


def ship(args: argparse.Namespace) -> dict:
    top = Path(git(Path(args.repo), "rev-parse", "--show-toplevel"))
    main_wt = worktrees(top)[0]["path"]
    base = args.base or remote_default(top) or default_base(top)
    branch = git(top, "branch", "--show-current")
    if not branch or branch in long_lived(top, base, remote=True):
        raise Stop(f"当前不在功能分支上（当前：{branch or 'detached HEAD'}，基线：{base}）；"
                   "基线、默认分支与 main/master 不走收口")
    if dirty_count(top):
        raise Stop("工作区有未提交改动，先提交或保全再收口")
    git(top, "fetch", "-q", "origin", base)
    commits = git(top, "log", "--reverse", "--format=%s", f"origin/{base}..HEAD").splitlines()
    if not commits:
        raise Stop(f"{branch} 相对 origin/{base} 没有新提交")
    head = sha_of(top, "HEAD")
    result = {"repo": str(top), "branch": branch, "base": base, "head": head}

    git(top, "push", "-q", "-u", "origin", branch)
    remote = git(top, "ls-remote", "origin", f"refs/heads/{branch}").split("\t")[0]
    if remote != head:
        raise Stop(f"推送后远端 {branch} 是 {remote[:12]}，不是本地 {head[:12]}")

    pr = read_pr(top, branch, base, head)
    if pr is None:
        title = args.title or (commits[0] if len(commits) == 1 else None)
        if not title:
            raise Stop(f"{branch} 有 {len(commits)} 个提交，用 --title 指定 PR 标题")
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write(Path(args.body_file).read_text() if args.body_file else
                     "## 提交\n\n" + "\n".join(f"- {c}" for c in commits) + "\n")
        run(gh_cmd(top, "pr", "create", "--base", base, "--head", branch, "--title", title, "--body-file", fh.name), top)
        Path(fh.name).unlink()
        pr = read_pr(top, branch, base, head)
    if pr is None or pr["headRefOid"] != head:
        raise Stop(f"PR 回读失败或 head 不是 {head[:12]}：{pr}")
    result.update(pr=pr["number"], url=pr["url"])

    if pr["state"] != "MERGED":
        result["ci"] = wait_checks(top, pr["number"], args.timeout, args.no_ci_grace, args.interval)
        if args.no_merge:
            result["stopped"] = "CI 已结束，按 --no-merge 停在合并前"
            return result
        wait_mergeable(top, pr["number"], base, head)
        run(gh_cmd(top, "pr", "merge", str(pr["number"]), f"--{args.method}", "--match-head-commit", head), top)
    merged = gh_json(top, "pr", "view", str(pr["number"]), "--json", "state,mergeCommit,baseRefName")
    if merged["state"] != "MERGED" or merged["baseRefName"] != base:
        raise Stop(f"PR #{pr['number']} 回读不是合入 {base} 的 MERGED：{merged}")
    merge_commit = (merged.get("mergeCommit") or {}).get("oid") or ""
    git(top, "fetch", "-q", "origin", base)
    if not SHA_RE.fullmatch(merge_commit) or run(
            ["git", "merge-base", "--is-ancestor", merge_commit, f"origin/{base}"], top, check=False).returncode:
        raise Stop(f"合并提交 {merge_commit or '(空)'} 不在 origin/{base} 上，未更新基线也未清理")
    result["merge_commit"] = merge_commit

    result["base_update"] = update_base(top, main_wt, base)
    result["cleanup"] = [] if args.keep_worktree else cleanup(main_wt, top, branch, head)
    return result


# ---------- clean ----------

CLEANABLE_WT_STATES = {"已合并且干净，可清理", "没有独有提交且干净，删除不丢内容"}


def occupying_pids(path: Path) -> list[int] | None:
    """cwd 落在 path 内（含自身）的进程 pid；无 /proc 时返回 None 表示检查不可用。

    ponytail: 只查 cwd，不查打开的 fd——cwd 在别处但开着 worktree 内文件的进程查不到；
    需要更严时升级为扫 /proc/*/fd。同机多 agent 场景下 cwd 检查足以挡住正在里面干活的进程。
    """
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():
        return None
    target = str(path.resolve())
    pids = []
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cwd = os.readlink(entry / "cwd")
        except OSError:
            continue  # 进程刚退出或无权限读，跳过
        if cwd == target or cwd.startswith(target + os.sep):
            pids.append(int(entry.name))
    return pids


def collect_repos(repos: list[str], roots: list[str] | None) -> list[Path]:
    """位置参数与 --roots 合并，按 realpath 去重（同一仓经不同路径传入只处理一次）；都未给时默认当前目录。"""
    out = [Path(r) for r in repos or ()]
    if not out and not roots:
        out = [Path(".")]
    for root in roots or ():
        out.extend(repos_under(Path(root)))
    seen, uniq = set(), []
    for repo in out:
        key = str(repo.resolve())
        if key not in seen:
            seen.add(key)
            uniq.append(repo)
    return uniq


def clean_repo(repo: Path, apply: bool, use_gh: bool) -> dict:
    """按 census 分类批量清理安全集：干净且已合并（或无独有提交）的 worktree、本地与远端分支。

    默认 dry-run 只出清单；--apply 才删除，删除沿用 ship 的保护（remove 不带 force、本地按 OID
    条件删、远端 force-with-lease 且 tip 必须等于盘点时的已合并 head），另查进程占用。基线、
    main/master 与长期分支永不删除；保留集只报告不动。清完 prune 失效登记并快进基线。
    """
    rep = census_repo(repo, fetch=True, use_gh=use_gh)
    repo = Path(rep["repo"])
    main_wt = worktrees(repo)[0]["path"]
    base = rep["base"]
    actions, held = [], []
    wt_targets, branch_targets, prunable = [], [], []
    for row in rep["items"]:
        if row["kind"] == "main":
            continue  # 主工作区与基线永远不动，基线更新交给 sync
        state = row.get("state", "")
        if row["kind"] == "worktree":
            if state.startswith("登记失效"):
                prunable.append(row)
            elif state not in CLEANABLE_WT_STATES:
                held.append(f"worktree {row['path']}（{row['branch'] or 'detached'}）：{state}")
            elif (pids := occupying_pids(Path(row["path"]))) is None:
                held.append(f"worktree {row['path']}：占用检查不可用（无 /proc），保守保留")
            elif pids:
                held.append(f"worktree {row['path']}：进程占用 pid={','.join(map(str, pids))}，保留")
            else:
                wt_targets.append(row)
        elif row["kind"] == "branch" and state == "已合并，可删除":
            branch_targets.append(row)
        else:
            held.append(f"分支 {row['branch']}：{state}")

    for row in wt_targets:
        label = f"worktree {row['path']}" + (f"（分支 {row['branch']}）" if row["branch"] else "（detached）")
        if not apply:
            actions.append(f"将删除 {label}：{row['state']}")
            if row["branch"]:
                actions.append(f"将删除本地与远端分支 {row['branch']}（存在且仍停在已合并 head 时）")
            continue
        wt = next((w for w in worktrees(repo) if w["path"] == Path(row["path"])), None)
        if wt is None or wt.get("HEAD") != row.get("head"):
            actions.append(f"worktree {row['path']} 已不在盘点时的 head，未清理")
            continue
        if row["branch"]:
            actions.extend(cleanup(main_wt, Path(row["path"]), row["branch"], row["head"]))
        else:
            proc = run(["git", "worktree", "remove", row["path"]], repo, check=False)
            actions.append(f"已删除 worktree {row['path']}（detached）" if proc.returncode == 0
                           else f"worktree 未删除（不强删）：{proc.stderr.strip()}")
    for row in branch_targets:
        if not apply:
            actions.append(f"将删除本地与远端分支 {row['branch']}：{row['state']}")
        else:
            actions.extend(delete_branch(main_wt, row["branch"], row["head"]))
    if prunable:
        if apply:
            run(["git", "worktree", "prune"], repo)
            actions.append(f"已 prune {len(prunable)} 条失效 worktree 登记")
        else:
            actions.append(f"将 prune {len(prunable)} 条失效 worktree 登记")

    if apply:
        try:
            main_note = sync_base(repo, base)["action"]
        except Stop as exc:
            main_note = f"main 未快进：{exc}"
    else:
        main_state = next((i.get("state", "") for i in rep["items"] if i["kind"] == "main"), "")
        main_note = f"基线现状：{main_state}（--apply 时快进）" if main_state else "dry-run 不动基线"
    return {"repo": str(repo), "base": base, "apply": apply, "fetch_error": rep["fetch_error"],
            "actions": actions, "held": held, "main": main_note}


def print_clean(reports: list[dict]) -> None:
    for rep in reports:
        mode = "apply" if rep["apply"] else "dry-run"
        print(f"## {rep['repo']}（基线 {rep['base']}，{mode}）")
        if rep["fetch_error"]:
            print(f"- fetch 失败，以下按本地已有的远端引用判读：{rep['fetch_error']}")
        for line in rep["actions"]:
            print(f"- {line}")
        for line in rep["held"]:
            print(f"- 保留 {line}")
        print(f"- {rep['main']}")
        if not rep["actions"] and not rep["held"]:
            print("- 无可清理对象")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("census", help="只读盘点仓库的 worktree、分支与基线状态")
    c.add_argument("repos", nargs="*", help="仓库路径；与 --roots 均未给时默认当前目录")
    c.add_argument("--roots", nargs="+", metavar="DIR", help="在根目录下（深度 ≤ 4）发现主仓，与 repos 合并去重")
    c.add_argument("--fetch", action="store_true", help="先 git fetch --prune 再比较")
    c.add_argument("--no-gh", action="store_true", help="不用 gh 识别 squash 合并")
    c.add_argument("--json", action="store_true", help="输出 JSON")

    y = sub.add_parser("sync", help="把本地基线安全快进到 origin/<base>")
    y.add_argument("--repo", default=".", help="仓库内任意路径，默认当前目录")
    y.add_argument("--base", help="基线分支，默认 origin/HEAD 指向的分支")

    cl = sub.add_parser("clean", help="批量清理已合并的 worktree 与分支并快进基线；默认 dry-run 只出清单")
    cl.add_argument("repos", nargs="*", help="仓库路径；与 --roots 均未给时默认当前目录")
    cl.add_argument("--roots", nargs="+", metavar="DIR", help="在根目录下（深度 ≤ 4）发现主仓，与 repos 合并去重")
    cl.add_argument("--apply", action="store_true", help="真正执行删除；不给则只出清单")
    cl.add_argument("--no-gh", action="store_true", help="不用 gh 识别 squash 合并")
    cl.add_argument("--json", action="store_true", help="输出 JSON")

    s = sub.add_parser("ship", help="推送当前分支并走完 PR → CI → 合并 → 更新基线 → 清理")
    s.add_argument("--repo", default=".", help="分支所在的工作区，默认当前目录")
    s.add_argument("--base", help="基线分支，默认 origin/HEAD 指向的分支")
    s.add_argument("--title", help="PR 标题；只有一个提交时默认用提交标题")
    s.add_argument("--body-file", help="PR 正文文件；默认列出提交")
    s.add_argument("--method", choices=["squash", "merge", "rebase"], default="squash")
    s.add_argument("--no-merge", action="store_true", help="CI 结束后停在合并前")
    s.add_argument("--keep-worktree", action="store_true", help="合并后不清理 worktree 与分支")
    s.add_argument("--timeout", type=int, default=3600, help="等待 CI 的上限秒数")
    s.add_argument("--no-ci-grace", type=int, default=90, help="一直没有 CI 时，等多少秒后按无 CI 处理")
    s.add_argument("--interval", type=int, default=15, help="轮询 CI 的间隔秒数")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "census":
            reports = [census_repo(repo, args.fetch, not args.no_gh)
                       for repo in collect_repos(args.repos, args.roots)]
            if args.json:
                print(json.dumps(reports, ensure_ascii=False, indent=2))
            else:
                print_census(reports)
        elif args.cmd == "sync":
            print(json.dumps(sync_base(Path(args.repo), args.base), ensure_ascii=False, indent=2))
        elif args.cmd == "clean":
            reports = [clean_repo(repo, args.apply, not args.no_gh)
                       for repo in collect_repos(args.repos, args.roots)]
            if args.json:
                print(json.dumps(reports, ensure_ascii=False, indent=2))
            else:
                print_clean(reports)
        else:
            print(json.dumps(ship(args), ensure_ascii=False, indent=2))
    except Stop as exc:
        print(f"停止：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
