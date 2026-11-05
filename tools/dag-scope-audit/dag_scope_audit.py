#!/usr/bin/env python3
"""
DAG Scope Audit — did a DAG child stay inside what its node prompt allowed?

Joins OMH DAG run records (OMH_HOME/runtime/dag) with the child sessions in
HERMES_HOME/state.db (read-only) through the `[dag:<run>/<node>]` goal marker,
then checks each child's tool calls against its node:

- tests / builds the node may not run (`prohibited_*` when the prompt or its NOT DO
  line forbids them, `unrequested_*` otherwise). VERIFY names the tests; a build node
  may compile and a verify/baseline node may build and test unless forbidden;
- side-effecting git commands whose verb the prompt does not request;
- writes outside `write_scope` (`foreign_scope_write` when the file belongs to another
  node of the same run that a repair does not fix; `check_role_write` for
  verify/baseline/review nodes). Files under /tmp, .state or .omh/artifacts, and
  OMH/Hermes runtime roots are not counted; relative paths no scope can place are
  listed under `unresolved`.

Findings are evidence for the parent's settle reason, not a verdict.

Usage:
    python3 tools/dag-scope-audit/dag_scope_audit.py --run RUN [--node ID]   # findings per child (JSON)
    python3 tools/dag-scope-audit/dag_scope_audit.py --days 30               # rates over recent DAG children
    python3 tools/dag-scope-audit/dag_scope_audit.py --days 30 --json

Read-only: the session DB is opened with mode=ro, and the DAG records are only
read. Paths default to $HERMES_HOME/state.db and $OMH_HOME/runtime/dag, with
$HERMES_HOME and $OMH_HOME falling back to ~/.hermes and ~/.omh; --db and
--omh-home override them.
"""

import argparse
import fnmatch
import glob
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

# ponytail: command and write detection is text-based. Shell redirection, `sed -i` and
# `python -c` writes are not seen, and a ctest named in VERIFY passes whatever filter it
# uses. Good enough to measure drift; a runtime guard (pre_tool_call) is the upgrade path.

HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
OMH_HOME = Path(os.getenv("OMH_HOME", Path.home() / ".omh"))

ROOTS: list[Path] = []  # runtime roots whose files are never a node's scoped work; set by audit()

DAG_MARK = re.compile(r"\[dag:([\w\-]+)/([\w\-]+)\]")
SECTION = re.compile(r"(?<![A-Za-z_])(TASK|DELIVERABLE|SCOPE|VERIFY|STOP WHEN|NOT DO|CONTEXT)\s*[:：]")
CHECK_ROLES = ("verify", "baseline", "review")
# Nodes stored before OMH recorded `role` run as build (OMH's default); a check-like label is reported, never trusted.
CHECK_LABEL = re.compile(r"(verif|(?:^|[-_ ])ver(?:[-_ ]|$)|baseline|review|audit|(?:^|[-_ ])qa(?:[-_ ]|$)|smoke|bench|probe"
                         r"|验证|审查|复核|基线)", re.I)

# --- what the prompt asks for ---------------------------------------------------------

CLAUSE = re.compile(r"[。；;，,\n]")
# A negation word right before an action verb: "不跑测试" forbids; "不改测试", "不声称全量测试通过" do not.
NEGATED = re.compile(r"(不|禁止|勿|严禁|无需|不必|不得|避免|don't|do not|never)\s*(?:要|再|去|做|进行|自行|额外|擅自)?[^，,。；;\n]{0,4}?"
                     r"(跑|运行|执行|启动|做|构建|编译|配置|提交|推送|run|build|commit|push)", re.I)
ASK_TEST = re.compile(r"(ctest|pytest|unittest|go test|cargo test|npm (?:run )?test|make (?:test|check)|Test_\w+|"
                      r"lint\.sh|precheck|测试|单测|回归|\btests?\b|复现|实跑|真实运行|实际运行|实际执行|命令输出|repro)", re.I)
ASK_BUILD = re.compile(r"(cmake|\bmake\b|ninja|编译|构建|\bbuild\b|configure)", re.I)
# Git words a prompt uses to ask for (or forbid) a git write, and the subcommands each one covers.
# English nouns ("the base commit SHA", "feature branch", "merge-base") are too common to count; Chinese verbs,
# PR, a commit/push that is not an id, and an explicit `git <verb>` in the prompt do.
# Letter-only boundaries: CJK characters count as \w, so `\b` never fires in "不commit".
GIT_WORD = re.compile(r"(git\s*写|git writes?|git\s+[a-z][a-z-]*|(?<![A-Za-z])commit(?![A-Za-z])(?!\s*(?:sha|hash|id\b|号|[0-9a-f]{7}))"
                      r"|(?<![A-Za-z])push(?![A-Za-z])|提交|推送|合并|分支|(?<![A-Za-z])PR(?![A-Za-z])|pull request)", re.I)
GIT_COVERS = {"commit": {"add", "commit"}, "提交": {"add", "commit"}, "push": {"push"}, "推送": {"push"},
              "pr": {"add", "commit", "push"}, "pull request": {"add", "commit", "push"}, "merge": {"merge"},
              "合并": {"merge"}, "branch": {"branch", "switch", "checkout"}, "分支": {"branch", "switch", "checkout"}}


GIT_NAMES = {"提交": "commit", "推送": "push", "合并": "merge", "分支": "branch", "pr": "push", "pull request": "push"}


def git_verbs(clauses: list[str], forbid: bool = False) -> set[str]:
    """Verbs a request covers (a commit request covers its `git add`), or, with ``forbid``, exactly the verbs named;
    "git 写" forbids every git write but requests none."""
    verbs: set[str] = set()
    for clause in clauses:
        for word in GIT_WORD.findall(clause):
            w = re.sub(r"\s+", " ", word.lower())
            if re.match(r"git ?(写|writes?)$", w):
                verbs |= {"*"} if forbid else set()
            elif w.startswith("git "):
                verbs.add(w.split()[1])
            else:
                verbs |= {GIT_NAMES.get(w, w)} if forbid else GIT_COVERS.get(w, {w})
    return verbs


def sections(prompt: str) -> dict[str, str]:
    marks = list(SECTION.finditer(prompt))
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(prompt)
        out[m.group(1)] = out.get(m.group(1), "") + prompt[m.end():end]
    return out


def asks(text: str, words: re.Pattern) -> bool:
    return any(words.search(c) for c in CLAUSE.split(text) if not NEGATED.search(c))


# "不跑全量测试", "不构建无必要目标" narrow the scope rather than forbid the action; the audit cannot tell
# a full run from a targeted one, so such clauses forbid nothing.
QUALIFIED = re.compile(r"(全部|全量|完整|整套|无必要|不必要|无关|多余|full|entire|whole|all\b|unrelated)", re.I)


def forbids(text: str, words: re.Pattern) -> bool:
    return any(words.search(c) for c in CLAUSE.split(text) if NEGATED.search(c) and not QUALIFIED.search(c))


def forbids_in_not_do(not_do: str, words: re.Pattern) -> bool:
    """NOT DO is a list of bans, so a clause naming the action forbids it unless it only narrows the scope."""
    return any(words.search(c) and not QUALIFIED.search(c) for c in CLAUSE.split(not_do))


def allowances(prompt: str, role: str = "build") -> dict[str, Any]:
    """What the node may do. VERIFY names the tests (no VERIFY section asks for none); the role adds its defaults --
    build compiles, verify/baseline build and test -- unless NOT DO or a negated clause forbids it."""
    sec = sections(prompt)
    not_do = sec.get("NOT DO", "")
    body = prompt.replace(not_do, "") if not_do else prompt
    verify = sec.get("VERIFY", "")
    out: dict[str, Any] = {"no_verify": "VERIFY" not in sec}
    out["test_forbidden"] = forbids_in_not_do(not_do, ASK_TEST) or forbids(body, ASK_TEST)
    out["build_forbidden"] = forbids_in_not_do(not_do, ASK_BUILD) or forbids(body, ASK_BUILD)
    checks = role in ("verify", "baseline")
    out["test"] = asks(verify, ASK_TEST) or (checks and not out["test_forbidden"])
    out["build"] = out["test"] or asks(verify, ASK_BUILD) or (role in ("build", "verify", "baseline")
                                                               and not out["build_forbidden"])
    clauses = CLAUSE.split(body)
    out["git_verbs"] = sorted(git_verbs([c for c in clauses if not NEGATED.search(c)]))
    out["git_verbs_forbidden"] = sorted(git_verbs([not_do] + [c for c in clauses if NEGATED.search(c)], forbid=True))
    return out


# --- what a terminal command does -----------------------------------------------------

HEREDOC = re.compile(r"(<<-?\s*['\"]?(\w+)['\"]?)[^\n]*\n.*?\n\2[ \t]*(?:\n|$)", re.S)
SPLIT = re.compile(r"\s*(?:&&|\|\||;|\n|\|)\s*")
WRAPPERS = [
    re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*\s+"),
    re.compile(r"^timeout\s+(?:-\S+\s+)*\d+\S*\s+"),
    re.compile(r"^flock\s+(?:-\w+\s+(?:\d+\s+)?)*\S+\s+"),
    re.compile(r"^nice(?:\s+-n\s*-?\d+)?\s+"),
    re.compile(r"^(?:time|env|sudo|command|stdbuf\s+\S+)\s+"),
    re.compile(r"^[({]\s*"),
]
TEST_RUN = re.compile(
    r"^(?:ctest\b|pytest\b|python3?\s+(?:-\S+\s+)*-m\s+(?:pytest|unittest)\b|python3?\s+\S*(?:run_tests?|verify_queue)\.py\b"
    r"|go\s+test\b|cargo\s+test\b|npm\s+(?:run\s+)?test\b|yarn\s+test\b"
    r"|make\s+(?:-\S+\s+(?:\S+\s+)?)*(?:test|check)\b|ninja\s+(?:-\S+\s+(?:\S+\s+)?)*test\b"
    r"|(?:ba)?sh\s+\S*(?:tools/health/\S+|run_tests?)\.sh|\S*/bin/tests/\S+|\.?/\S*(?:Test_\w+|_tests?)\b)")
NOT_A_RUN = re.compile(r"(?:\s-N\b|--show-only|--version|--help|--list|--collect-only|\s-h\b)")
BUILD_RUN = re.compile(r"^(?:cmake\s+--build\b|cmake\s+(?:-\S+\s+)*-[SB]|make\b|ninja\b)")
# Index-only moves (`reset` without --hard, `restore --staged`) are left out: they lose no work.
GIT_PREFIX = re.compile(r"^git\s+(?:(?:-C|-c)\s+\S+\s+|--no-pager\s+)*")
# `add -N` only records intent (it makes new files show in `git diff`), so it is left out like `restore --staged`.
GIT_MUT = re.compile(r"(?:commit|push|add(?!\s+(?:-N|--intent-to-add)\b)|rm|mv|reset\s+(?:\S+\s+)*--hard|checkout\s+(?:--|-f|-B)|switch|stash(?!\s+(?:list|show))"
                     r"|rebase|merge(?![\w-])|cherry-pick|clean|restore(?!\s+--staged)|am|apply(?!\s+(?:--check|--stat))"
                     r"|branch\s+-[dDmM]|tag\s+(?!-l|--list|--contains)|update-index|update-ref|worktree\s+(?:add|remove|move|prune)"
                     r"|config\s+(?!(?:--get|--list|-l)\b)\S+\s+\S+)\b")


def strip_wrappers(seg: str) -> str:
    seg = seg.strip()
    moved = True
    while moved:
        moved = False
        for rx in WRAPPERS:
            m = rx.match(seg)
            if m and m.end() < len(seg):
                seg, moved = seg[m.end():], True
                break
    return seg


def classify(command: str) -> list[tuple[str, str]]:
    """(kind, segment) for each test / build / git segment of a shell command; heredoc bodies are skipped."""
    out = []
    for seg in SPLIT.split(HEREDOC.sub(r"\1\n", command)):
        s = strip_wrappers(seg)
        if not s:
            continue
        if TEST_RUN.match(s) and not NOT_A_RUN.search(s):
            out.append(("test", s[:160]))
        elif BUILD_RUN.match(s) and not NOT_A_RUN.search(s):
            out.append(("build", s[:160]))
        elif (g := GIT_PREFIX.match(s)) and GIT_MUT.match(s, g.end()):
            out.append(("git", s[:160]))
    return out


# --- what a write touches -------------------------------------------------------------

# Only determinable runtime roots are skipped -- a directory merely named out/ or reports/ can hold real work.
# Tool-specific roots only. A generic `out/`, `reports/` or `tmp/` segment can hold real work, so it is kept.
NOT_WORK_SEGMENT = re.compile(r"/(?:\.omh/artifacts|\.state)/")


def not_work(path: str, roots: list[Path]) -> bool:
    p = Path(path).expanduser()
    return (path.startswith("/tmp/") or bool(NOT_WORK_SEGMENT.search(path))
            or any(p == r or p.is_relative_to(r) for r in roots))


def runtime_roots(omh_home: Path) -> list[Path]:
    """OMH's own run records and artifacts, and the session scratch space: never a node's scoped work."""
    return [omh_home / "runtime", omh_home / "artifacts", Path(HERMES_HOME) / "cache" / "scratch",
            Path(HERMES_HOME) / "deliverables"]
ALIAS_SCOPE = re.compile(r"^[A-Z]{1,6}(?:/|$)")


def in_scope(path: str, scope: list[str]) -> bool:
    if not path.startswith("/"):
        return rel_in_scope(path, scope)
    for entry in scope:
        if fnmatch.fnmatch(path, entry) or fnmatch.fnmatch(path, "*/" + entry.lstrip("/")):
            return True
        stem = re.split(r"[*?\[]", entry)[0].rstrip("/")
        rel = stem.lstrip("/")
        if stem and (path == stem or path.startswith(stem + "/") or f"/{rel}/" in path or path.endswith("/" + rel)):
            return True
    return False


def rel_in_scope(path: str, scope: list[str]) -> bool:
    """A relative path is in scope when it starts at a relative entry, or at some tail of an absolute entry."""
    parts = [p for p in path.split("/") if p not in ("", ".")]
    for entry in scope:
        if fnmatch.fnmatch(path, entry.lstrip("/")):
            return True
        stem = [p for p in re.split(r"[*?\[]", entry)[0].rstrip("/").split("/") if p]
        tails = [stem] if not entry.startswith("/") else [stem[i:] for i in range(len(stem))]
        if any(t and parts[:len(t)] == t for t in tails):
            return True
    return False


def written_paths(calls: list[tuple[str, dict]]) -> list[str]:
    paths = []
    for name, args in calls:
        if name == "write_file" and args.get("path"):
            paths.append(str(args["path"]))
        elif name == "patch":
            if args.get("path"):
                paths.append(str(args["path"]))
            paths += [m.strip() for m in re.findall(r"^\*\*\* (?:Update|Add|Delete) File:\s*(.+)$",
                                                     str(args.get("patch", "")), flags=re.M)]
    return [p for p in paths if p and not not_work(p, ROOTS)]


# --- joining runs, nodes and child sessions ---------------------------------------------

def load_runs(omh_home: Path) -> dict[str, list[tuple[dict, Path]]]:
    runs: dict[str, list[tuple[dict, Path]]] = {}
    for f in glob.glob(str(omh_home / "runtime" / "dag" / "*" / "*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("run") and isinstance(record.get("nodes"), list):
            runs.setdefault(record["run"], []).append((record, Path(f).parent))
    return runs


def pick_record(candidates: list[tuple[dict, Path]], node_id: str, started: float):
    """Run names repeat across sessions: take the latest record defined before the child started."""
    have = [c for c in candidates if any(n.get("id") == node_id for n in c[0]["nodes"])]
    before = [c for c in have if (c[0].get("defined_at") or 0) <= started]
    pool = before or have
    return max(pool, key=lambda c: c[0].get("defined_at") or 0) if pool else None


def connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.execute("pragma query_only=1")
    return con


def dag_children(con: sqlite3.Connection, since: float, run: str | None) -> list[dict]:
    rows = con.execute(
        "select s.id, s.started_at, (select content from messages m where m.session_id = s.id and m.role = 'user' "
        "order by m.id limit 1) from sessions s where s.source = 'subagent' and s.started_at >= ? order by s.started_at",
        (since,)).fetchall()
    out = []
    for sid, started, first in rows:
        marks = DAG_MARK.findall(first or "")
        if marks and (run is None or marks[-1][0] == run):
            out.append({"session": sid, "started": started or 0.0, "run": marks[-1][0], "node": marks[-1][1]})
    return out


def tool_calls(con: sqlite3.Connection, sid: str) -> list[tuple[str, dict]]:
    out = []
    for (raw,) in con.execute("select tool_calls from messages where session_id = ? and role = 'assistant' "
                              "and tool_calls is not null order by id", (sid,)):
        try:
            calls = json.loads(raw)
        except ValueError:
            continue
        for call in calls if isinstance(calls, list) else []:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            out.append((fn.get("name") or "", args if isinstance(args, dict) else {}))
    return out


def node_role(node: dict) -> tuple[str, str]:
    """(role, source). A recorded role wins. A record without one predates OMH's role field: dag_run.node_role reads
    it from the label (`guessed_role`), so this audit does too -- but only to tighten (check-role writes), never to
    grant the test/build defaults, because the guess may be wrong."""
    if node.get("role"):
        return str(node["role"]), "recorded"
    looks = CHECK_LABEL.search(f"{node.get('id', '')} {node.get('label', '')}")
    if looks and not str(node.get("origin", "")).startswith("repair:"):
        return "verify", "legacy_label"
    return "build", "legacy_label"


def audit_child(child: dict, record: dict, calls: list[tuple[str, dict]]) -> dict:
    node = next(n for n in record["nodes"] if n.get("id") == child["node"])
    role, role_source = node_role(node)
    # A label-guessed role must not widen permissions: it only enables the stricter check-role write rule.
    allow = allowances(str(node.get("prompt", "")), "build" if role_source == "legacy_label" else role)
    findings: list[dict] = []
    for name, args in calls:
        if name != "terminal":
            continue
        for kind, seg in classify(str(args.get("command", ""))):
            if kind == "git":
                verb = GIT_PREFIX.sub("", seg, count=1).split()[0]
                if verb in allow["git_verbs"]:
                    continue  # requested; a same-verb limit ("不 force push 到 main") names a target we cannot parse
                forbidden = bool({verb, "*"} & set(allow["git_verbs_forbidden"]))
            elif allow[kind]:
                continue
            else:
                forbidden = allow[f"{kind}_forbidden"]
            findings.append({"kind": f"{'prohibited' if forbidden else 'unrequested'}_{kind}", "evidence": seg})

    scope = list(node.get("write_scope") or [])
    unresolved: list[str] = []
    if any(ALIAS_SCOPE.match(s) for s in scope):
        unresolved.append("write_scope uses an alias; writes not checked")
    elif not scope and role not in CHECK_ROLES:
        unresolved.append("no write_scope declared; writes not checked")
    else:
        repairs = str(node.get("origin", "")).partition("repair:")[2]
        others = [(n["id"], n.get("write_scope") or []) for n in record["nodes"] if n.get("id") not in (node["id"], repairs)]
        # OMH's is_producer: a verify node is never a producer, so a recorded verify writing a work file is
        # reported even inside its scope. A label-guessed role is too uncertain to tighten that way: it only
        # labels the record (role_source), and its writes are judged as a build node's.
        strict = role == "verify" and role_source == "recorded"
        if strict:
            scope = []
        for path in dict.fromkeys(written_paths(calls)):
            if in_scope(path, scope) or (repairs and any(in_scope(path, n.get("write_scope") or [])
                                                         for n in record["nodes"] if n.get("id") == repairs)):
                continue
            owner = next((nid for nid, sc in others if sc and in_scope(path, sc)), None)
            if not path.startswith("/") and not owner:
                unresolved.append(path)  # no scope places it: cwd unknown, so neither in nor out
                continue
            # a label-guessed check role is too uncertain to call a violation: it is judged as a build node's write
            checked = role in CHECK_ROLES and role_source == "recorded"
            kind = "check_role_write" if checked else "foreign_scope_write" if owner else "out_of_scope_write"
            findings.append({"kind": kind, "evidence": path, **({"owner": owner} if owner else {})})

    return {"run": record["run"], "node": node["id"], "session": child["session"], "role": role, "role_source": role_source,
            "allow": {k: allow[k] for k in ("test", "build", "git_verbs", "no_verify")}, "findings": findings,
            "unresolved": unresolved}


def audit(db: Path, omh_home: Path, since: float, run: str | None = None, node: str | None = None) -> list[dict]:
    global ROOTS
    ROOTS = runtime_roots(omh_home)
    runs = load_runs(omh_home)
    con = connect(db)
    try:
        children = [c for c in dag_children(con, since, run) if node is None or c["node"] == node]
        results = []
        for child in children:
            picked = pick_record(runs.get(child["run"], []), child["node"], child["started"])
            if picked:
                results.append(audit_child(child, picked[0], tool_calls(con, child["session"])))
        return results
    finally:
        con.close()


def summarize(results: list[dict]) -> dict[str, Any]:
    def rates(rows: list[dict]) -> dict[str, str]:
        hit = Counter(k for r in rows for k in {f["kind"] for f in r["findings"]})
        n = len(rows)
        return {k: f"{v}/{n} = {100 * v / n:.0f}%" for k, v in sorted(hit.items())} | {
            "any": f"{sum(1 for r in rows if r['findings'])}/{n}",
            "(unresolved, not checked)": f"{sum(1 for r in rows if r['unresolved'])}/{n}"} if n else {}
    build = [r for r in results if r["role"] == "build"]  # writers; check nodes may run tests
    return {"children": len(results), "build_children": len(build), "all": rates(results), "build": rates(build)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("--run", help="audit one run id; prints per-child findings as JSON")
    ap.add_argument("--node", help="limit --run to one node id")
    ap.add_argument("--days", type=float, default=30.0, help="child sessions started in the last N days (summary)")
    ap.add_argument("--json", action="store_true", help="summary as JSON")
    ap.add_argument("--db", type=Path, default=HERMES_HOME / "state.db",
                    help="Hermes session DB, read-only (default: $HERMES_HOME/state.db)")
    ap.add_argument("--omh-home", type=Path, default=OMH_HOME,
                    help="OMH home holding runtime/dag (default: $OMH_HOME)")
    a = ap.parse_args()
    if not a.db.exists():
        print(f"state.db not found: {a.db}", file=sys.stderr)
        return 2
    if a.run:
        print(json.dumps(audit(a.db, a.omh_home, 0.0, a.run, a.node), ensure_ascii=False, indent=2))
        return 0
    results = audit(a.db, a.omh_home, time.time() - a.days * 86400)
    summary = summarize(results)
    if a.json:
        print(json.dumps(summary | {"results": results}, ensure_ascii=False, indent=2))
        return 0
    print(f"DAG children (last {a.days:g} days): {summary['children']}, build-role: {summary['build_children']}")
    for label in ("all", "build"):
        print(f"\n[{label}] children with >=1 finding of each kind")
        for kind, rate in summary[label].items():
            print(f"  {kind:26} {rate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
