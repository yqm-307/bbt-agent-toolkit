#!/usr/bin/env python3
"""Generic prompt-asset health and reference checker.

The tool scans the selected repository; it does not assume this repository's
layout, profile, baseline, host, or CI. It keeps the useful reference-checking
part of the former skill index inside the same command and never writes scan
outputs unless the caller explicitly requests a report or snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

SCHEMA = "prompt-health/v1"
TEXT_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".json"}
ASSET_DIRS = {"skills", "agents", "docs", "plugins", "tools", "workflows"}
EXCLUDED_PARTS = {".git", ".state", ".venv", "venv", "node_modules", "build", "dist", "coverage"}
SKILL_LIMIT = 15_000
DOC_LIMIT = 40_960
MUST_RE = re.compile(r"必须|不得|禁止|应当|须|强制|一律|务必|不准|不许|\b(?:MUST|NEVER|ALWAYS|REQUIRED)\b", re.I)
UNSURE_RE = re.compile(r"可能|建议|酌情|视情况|尽量|通常|原则上|大概|自行")
FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
NAME_RE = re.compile(r"^name\s*:\s*(.+?)\s*$", re.M)
RELATED_RE = re.compile(r"^related_skills\s*:\s*(.*)$", re.M)
TOKEN_RE = re.compile(r"[a-z][a-z0-9]+(?:-[a-z0-9]+)*")


def git_files(root: Path) -> list[str] | None:
    try:
        p = subprocess.run(["git", "ls-files", "-z"], cwd=root, text=True,
                           capture_output=True, check=False)
    except OSError:
        return None
    if p.returncode != 0:
        return None
    return sorted(x for x in p.stdout.split("\0") if x)


def in_scope(rel: str) -> bool:
    p = Path(rel)
    if any(part in EXCLUDED_PARTS for part in p.parts):
        return False
    if p.name in {"AGENTS.md", "HERMES.md", "README.md"} and len(p.parts) == 1:
        return True
    return bool(p.parts and p.parts[0] in ASSET_DIRS and p.suffix.lower() in TEXT_SUFFIXES)


def asset_paths(root: Path) -> list[str]:
    tracked = git_files(root)
    if tracked is not None:
        return [p for p in tracked if in_scope(p)]
    rows = []
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if in_scope(rel):
                rows.append(rel)
    return sorted(rows)


def parse_skill(path: Path, rel: str) -> tuple[str, list[str], str]:
    text = path.read_text(encoding="utf-8")
    match = FM_RE.match(text)
    front = match.group(1) if match else ""
    body = text[match.end():] if match else text
    name_match = NAME_RE.search(front)
    name = name_match.group(1).strip().strip("\"'") if name_match else path.parent.name
    related: list[str] = []
    related_match = RELATED_RE.search(front)
    if related_match:
        raw = related_match.group(1).strip()
        if raw.startswith("[") and "]" in raw:
            related = [x.strip().strip("\"'") for x in raw[1:raw.index("]")].split(",") if x.strip()]
        elif not raw:
            for line in front[related_match.end():].splitlines():
                item = re.fullmatch(r"\s*-\s*([a-z][a-z0-9-]*)\s*", line)
                if item:
                    related.append(item.group(1))
    return name, sorted(set(related)), body


def reference_findings(root: Path) -> list[dict]:
    skills: dict[str, tuple[str, list[str], str]] = {}
    findings: list[dict] = []
    for rel in asset_paths(root):
        if not (rel.startswith("skills/") and rel.endswith("/SKILL.md")):
            continue
        try:
            skills[parse_skill(root / rel, rel)[0]] = (rel, *parse_skill(root / rel, rel)[1:])
        except (OSError, UnicodeError, ValueError) as exc:
            findings.append({"id": "REF-UNREADABLE", "severity": "ERROR", "path": rel,
                             "detail": str(exc)})
    duplicates: dict[str, list[str]] = defaultdict(list)
    for name, (rel, _, _) in skills.items():
        duplicates[name].append(rel)
    for name, paths in duplicates.items():
        if len(paths) > 1:
            findings.append({"id": f"REF-DUPLICATE-{name}", "severity": "ERROR",
                             "path": ", ".join(paths), "detail": f"重复 skill 名称：{name}"})
    names = set(skills)
    for name, (rel, related, body) in skills.items():
        for dep in related:
            if dep not in names:
                findings.append({"id": f"REF-MISSING-{name}-{dep}", "severity": "ERROR",
                                 "path": rel, "detail": f"related_skills 引用不存在：{dep}"})
        mentions = {token for token in TOKEN_RE.findall(body) if token in names and token != name}
        undeclared = sorted(mentions - set(related))
        if undeclared:
            findings.append({"id": f"REF-UNDECLARED-{name}", "severity": "INFO",
                             "path": rel, "detail": "正文提及但未声明的 skill：" + ", ".join(undeclared)})
    return findings


def scan(root: Path) -> tuple[list[dict], dict, dict[str, str]]:
    rows: list[dict] = []
    corpus: dict[str, str] = {}
    for rel in asset_paths(root):
        path = root / rel
        if path.is_symlink():
            continue
        try:
            data = path.read_bytes()
            text = data.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            rows.append({"path": rel, "error": str(exc)})
            continue
        corpus[rel] = hashlib.sha256(data).hexdigest()
        body = FM_RE.sub("", text, count=1)
        rows.append({"path": rel, "bytes": len(data), "must": len(MUST_RE.findall(body)),
                     "unsure": len(UNSURE_RE.findall(body)),
                     "digest": hashlib.sha256(data).hexdigest()})
    findings = reference_findings(root)
    by_digest: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if "digest" in row and row["path"].endswith(".md"):
            by_digest[row["digest"]].append(row["path"])
        if "error" in row:
            findings.append({"id": "DATA-UNREADABLE", "severity": "ERROR", "path": row["path"], "detail": row["error"]})
        elif row["path"].endswith("/SKILL.md") and row["bytes"] > SKILL_LIMIT:
            findings.append({"id": "SIZE-SKILL", "severity": "WARN", "path": row["path"],
                             "detail": f"{row['bytes']} B > {SKILL_LIMIT} B"})
        elif row["path"].endswith(".md") and row["bytes"] > DOC_LIMIT:
            findings.append({"id": "SIZE-DOC", "severity": "INFO", "path": row["path"],
                             "detail": f"{row['bytes']} B > {DOC_LIMIT} B（候选）"})
    for digest, paths in by_digest.items():
        if len(paths) > 1:
            findings.append({"id": "DUPLICATE-CONTENT", "severity": "WARN",
                             "path": ", ".join(sorted(paths)), "detail": f"相同 Markdown 内容 {len(paths)} 份"})
    metrics = {"files": sum("digest" in r for r in rows),
               "bytes": sum(r.get("bytes", 0) for r in rows),
               "unreadable": sum("error" in r for r in rows),
               "reference_errors": sum(f["severity"] == "ERROR" and f["id"].startswith("REF-") for f in findings),
               "reference_infos": sum(f["severity"] == "INFO" and f["id"].startswith("REF-") for f in findings),
               "size_warnings": sum(f["id"].startswith("SIZE-") for f in findings),
               "duplicate_groups": sum(f["id"] == "DUPLICATE-CONTENT" for f in findings)}
    return findings, metrics, corpus


def print_report(root: Path, findings: list[dict], metrics: dict, out=None) -> None:
    lines = ["# Prompt asset health report", "", f"Root: `{root}`", "",
             "| Metric | Value |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(metrics.items())]
    lines += ["", "## Findings", ""]
    if not findings:
        lines.append("No findings.")
    else:
        for f in findings:
            lines.append(f"- **{f['severity']}** `{f['id']}` `{f['path']}` — {f['detail']}")
    text = "\n".join(lines) + "\n"
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="要扫描的仓库根目录，默认当前目录")
    ap.add_argument("--report", help="写人读报告；不传则输出到 stdout")
    ap.add_argument("--snapshot", help="显式写入 JSON 快照")
    ap.add_argument("--check", help="与 JSON 快照比较当前语料和指标")
    ap.add_argument("--gate", action="store_true", help="只报告引用错误、体量超限和重复内容；新增命中返回 1")
    ap.add_argument("--verbose", action="store_true", help="gate 时列出 INFO 引用提示")
    args = ap.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    findings, metrics, corpus = scan(root)
    errors = [f for f in findings if f["severity"] in {"ERROR", "WARN"}]
    if args.gate:
        selected = [f for f in findings if f["severity"] in {"ERROR", "WARN"} or args.verbose]
        for f in selected:
            print(f"GATE {f['severity']}: {f['id']} {f['path']} — {f['detail']}")
        return 1 if errors else 0
    if args.snapshot:
        payload = {"schema": SCHEMA, "metrics": metrics, "corpus": corpus}
        path = Path(args.snapshot).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.check:
        try:
            old = json.loads(Path(args.check).read_text(encoding="utf-8"))
            if old.get("schema") != SCHEMA:
                print("CHECK:ERROR unsupported snapshot schema", file=sys.stderr)
                return 2
            changed = old.get("corpus") != corpus or old.get("metrics") != metrics
            print("CHECK:CHANGED" if changed else "CHECK:UNCHANGED")
            return 1 if changed else 0
        except (OSError, ValueError, TypeError) as exc:
            print(f"CHECK:ERROR {exc}", file=sys.stderr)
            return 2
    print_report(root, findings, metrics, args.report)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
