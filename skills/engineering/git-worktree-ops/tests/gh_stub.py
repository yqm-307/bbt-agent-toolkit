#!/usr/bin/env python3
"""测试用的 gh 替身：只实现 git_closeout.py 用到的子命令，PR 状态存在 $GH_STUB_STATE。

合并用「把 PR head 推到远端基线」模拟（分支基于基线时等同快进合并）。
state 里可用的钩子：
- checks：字符串或字符串列表（按调用次序逐次弹出，末项保持）；"none"、"malformed" 有特殊行为；
  checks_exit 覆盖退出码。
- checks_rounds：[[[名字, 状态], ...], ...] 按调用次序逐轮弹出，末轮保持，模拟按名字跟踪的检查。
- steal_base：pr checks 调用时把 PR 的 baseRefName 改成它，模拟等待期间被改投。
- post_merge：pr merge 后逐条用 shell 执行的命令，模拟等待/合并期间外部对仓库的改动。
"""

import json
import os
import subprocess
import sys

STATE = os.environ["GH_STUB_STATE"]


def load():
    with open(STATE) as fh:
        return json.load(fh)


def save(state):
    with open(STATE, "w") as fh:
        json.dump(state, fh)


def opt(args, name):
    return args[args.index(name) + 1] if name in args else None


def find(state, key):
    prs = [p for p in state["prs"] if str(p["number"]) == key or p["headRefName"] == key]
    return prs[-1] if prs else None


def print_checks(rows, state):
    for name, status in rows:
        print(f"{name}\t{status}\t1s\thttps://example.invalid/run\t")
    return 0 if all(status == "pass" for _, status in rows) else 1


def main(argv):
    state = load()
    state.setdefault("calls", []).append(argv)
    save(state)
    if argv[:2] == ["pr", "view"]:
        pr = find(state, argv[2])
        if pr is None:
            print("no pull requests found", file=sys.stderr)
            return 1
        print(json.dumps({k: pr.get(k) for k in opt(argv, "--json").split(",")}))
        return 0
    if argv[:2] == ["pr", "create"]:
        head = opt(argv, "--head")
        sha = subprocess.run(["git", "ls-remote", "origin", f"refs/heads/{head}"],
                             capture_output=True, text=True, check=True).stdout.split("\t")[0]
        number = len(state["prs"]) + 1
        state["prs"].append({"number": number, "url": f"https://example.invalid/pull/{number}",
                             "state": "OPEN", "headRefName": head, "headRefOid": sha,
                             "baseRefName": opt(argv, "--base"), "isDraft": False,
                             "mergeStateStatus": state.get("merge_state", "CLEAN"),
                             "reviewDecision": "", "mergeCommit": None})
        save(state)
        return 0
    if argv[:2] == ["pr", "checks"]:
        pr = find(state, argv[2])
        if state.get("steal_base") and pr:  # 模拟等待期间 PR 被改投到其他基线
            pr["baseRefName"] = state["steal_base"]
            save(state)
        rounds = state.get("checks_rounds")
        if rounds:
            rows = rounds[0]
            if len(rounds) > 1:
                state["checks_rounds"] = rounds[1:]
                save(state)
            return print_checks(rows, state)
        mode = state.get("checks", "pass")
        if isinstance(mode, list):  # 按调用次序逐次弹出，末项保持
            mode, rest = mode[0], mode[1:]
            if rest:
                state["checks"] = rest
                save(state)
        if mode == "none":
            name = pr["headRefName"] if pr else "?"
            print(f"no checks reported on the '{name}' branch", file=sys.stderr)
            return 1
        if mode == "malformed":  # 不足 3 个 tab 分隔列的坏行
            print("build broken-output")
            return 1
        print(f"build\t{mode}\t1s\thttps://example.invalid/run\t")
        return state.get("checks_exit", 0 if mode == "pass" else 1)
    if argv[:2] == ["pr", "merge"]:
        pr = find(state, argv[2])
        if opt(argv, "--match-head-commit") != pr["headRefOid"]:
            print("head commit mismatch", file=sys.stderr)
            return 1
        subprocess.run(["git", "push", "-q", "origin", f"{pr['headRefOid']}:refs/heads/{pr['baseRefName']}"],
                       check=True)
        pr.update(state="MERGED", mergeCommit={"oid": pr["headRefOid"]})
        save(state)
        for cmd in state.get("post_merge", []):  # 模拟等待/合并期间外部对仓库的改动
            subprocess.run(cmd, shell=True, capture_output=True)
        return 0
    if argv[:2] == ["pr", "list"]:
        head, base, want = opt(argv, "--head"), opt(argv, "--base"), opt(argv, "--state") or "open"
        fields = (opt(argv, "--json") or "").split(",")
        rows = [p for p in reversed(state["prs"]) if p["headRefName"] == head
                and (base is None or p["baseRefName"] == base)
                and (want == "all" or p["state"] == want.upper())]
        print(json.dumps([{k: p.get(k, False if k == "isCrossRepository" else None) for k in fields}
                          for p in rows]))
        return 0
    print(f"gh stub: unsupported {argv}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
