#!/usr/bin/env python3
"""把提示词文件拆成带编号的句子清单，并一次性做完机械检查。

清单供主 agent 与各路子代理共用：子代理按编号引用、只看自己负责的部分，
不必各自重读全文，也不必重复做路径存在性、措辞标记、近似重复这类机械判断。
所有标记都是启发式候选，不是结论；是否构成噪音由读懂语义的人或模型判断。

只读：除 --out 指定的文件外不写任何东西，不联网，不修改被扫描文件。
"""

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

# 词表刻意保守：宁可漏标，也不让标记多到失去筛选作用。
FLAG_PATTERNS = {
    "absolute": re.compile(
        r"必须|务必|一律|始终|总是|永远|绝不|禁止|严禁|不得|只能|只允许|一定要"
        r"|\b(?:must|never|always|critical)\b",
        re.I,
    ),
    "gate": re.compile(
        r"授权|批准|审批|确认|先问|询问|请示|停下|暂停|等待用户|等用户"
        r"|\b(?:ask|confirm\w*|approv\w*|permission|authori[sz]\w*)\b",
        re.I,
    ),
    "review": re.compile(r"审查|复审|评审|审核|\breview\w*\b", re.I),
    "vague": re.compile(
        r"适当|适度|尽量|尽可能|合理|必要时|视情况|酌情|关键|重要|简单|非\s*trivial"
        r"|\b(?:trivial|appropriate\w*|reasonabl\w*|as needed|where possible)\b",
        re.I,
    ),
}
# 句中出现条件或例外，说明绝对化措辞已有范围限定。
CONDITION = re.compile(
    r"如果|若|当.{0,40}?时|除非|仅在|只在|仅当|只有.{0,30}?才|否则|例外|以外|之外"
    r"|\b(?:if|when|unless|except|only)\b",
    re.I,
)

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
FENCE = re.compile(r"^\s*(```|~~~)")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}")
SENTENCE_END = re.compile(r"(?<=[。；！？])|(?<=[.!?;])\s+")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
BACKTICK = re.compile(r"`([^`\n]+)`")
URL = re.compile(r"https?://[^\s)>`\"'，。；]+")
PATH_EXT = re.compile(
    r"\.(?:md|markdown|py|sh|bash|json|ya?ml|toml|txt|ini|cfg|cmake|hpp|h|cc|cpp|c|js|mjs|ts)$",
    re.I,
)
PLACEHOLDER = re.compile(r"[<>{}*$\s]|\.\.\.")

ELLIPSIS = re.compile(r"…+|\.{3,}")

SHINGLE = 3
MIN_DUP_CHARS = 12
LARGE_INVENTORY = 600


def split_blocks(lines):
    """按 Markdown 结构切块：段落、列表项、表格行、代码块、frontmatter。"""
    blocks, headings = [], []
    i, n = 0, len(lines)

    def heading_path():
        return " > ".join(title for _, title in headings)

    if n and lines[0].strip() == "---":
        end = next((j for j in range(1, n) if lines[j].strip() == "---"), None)
        if end is not None:
            blocks.append(("frontmatter", 1, "", "\n".join(lines[1:end])))
            i = end + 1

    para, para_line, para_kind = [], 0, "para"

    def flush():
        nonlocal para
        if para:
            blocks.append((para_kind, para_line, heading_path(), " ".join(para)))
            para = []

    while i < n:
        raw = lines[i]
        stripped = raw.strip()
        if FENCE.match(raw):
            flush()
            start, body = i + 1, []
            i += 1
            while i < n and not FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            blocks.append(("code", start, heading_path(), "\n".join(body)))
            i += 1
            continue
        heading = HEADING.match(raw)
        if heading:
            flush()
            level = len(heading.group(1))
            headings[:] = [h for h in headings if h[0] < level] + [(level, heading.group(2))]
            i += 1
            continue
        if not stripped or (stripped.startswith("<!--") and stripped.endswith("-->")):
            flush()
            i += 1
            continue
        if stripped.startswith("|"):
            flush()
            if not TABLE_SEP.match(stripped):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                blocks.append(("table", i + 1, heading_path(), " | ".join(cells)))
            i += 1
            continue
        if LIST_ITEM.match(raw):
            flush()
            para, para_line, para_kind = [LIST_ITEM.sub("", raw).strip()], i + 1, "list"
            i += 1
            continue
        if not para:
            para_line, para_kind = i + 1, "para"
        para.append(stripped)
        i += 1
    flush()
    return blocks


def sentences(text):
    return [s.strip() for s in SENTENCE_END.split(text) if s and s.strip()]


def flags_for(text):
    found = [name for name, pat in FLAG_PATTERNS.items() if pat.search(text)]
    if "absolute" in found and not CONDITION.search(text):
        found.append("unscoped_absolute")
    return found


def resolve_ref(target, base_dir, root):
    """返回 (状态, 解析后的路径)；状态为 ok / missing，无法判断时返回 None。"""
    target = target.split("#", 1)[0].strip()
    if not target or PLACEHOLDER.search(target):
        return None
    expanded = os.path.expanduser(target)
    candidates = [Path(expanded)] if os.path.isabs(expanded) else [base_dir / expanded, root / expanded]
    for cand in candidates:
        if cand.exists():
            return "ok", str(cand.resolve())
    # 不带目录的裸文件名（按名提及别处的脚本）、无扩展名的分支名或类型名都不报缺失，避免假阳性。
    if "/" in target and (PATH_EXT.search(target) or target.endswith("/")):
        return "missing", str(candidates[0])
    return None


def refs_in(text, base_dir, root):
    refs, seen = [], set()
    for target in MD_LINK.findall(text) + BACKTICK.findall(text):
        if target.startswith(("http://", "https://", "mailto:", "#")) or target in seen:
            continue
        seen.add(target)
        looks_like_path = "/" in target or PATH_EXT.search(target)
        if not looks_like_path:
            continue
        resolved = resolve_ref(target, base_dir, root)
        if resolved:
            refs.append({"target": target, "status": resolved[0], "resolved": resolved[1]})
    for url in URL.findall(text):
        if url not in seen:
            seen.add(url)
            refs.append({"target": url, "status": "url", "resolved": None})
    return refs


def normalize(text):
    return "".join(
        ch.lower() for ch in text if not ch.isspace() and unicodedata.category(ch)[0] not in "PS"
    )


def near_duplicates(units, threshold, limit=3000):
    candidates = [u for u in units if u["kind"] != "code"]
    if len(candidates) > limit:
        return [], f"句子数 {len(candidates)} 超过 {limit}，跳过近似重复检查"
    shingles = []
    for unit in candidates:
        norm = normalize(unit["text"])
        if len(norm) < MIN_DUP_CHARS:
            shingles.append(None)
            continue
        shingles.append({norm[k:k + SHINGLE] for k in range(len(norm) - SHINGLE + 1)})
    pairs = []
    for a in range(len(candidates)):
        if shingles[a] is None:
            continue
        for b in range(a + 1, len(candidates)):
            if shingles[b] is None:
                continue
            inter = len(shingles[a] & shingles[b])
            if not inter:
                continue
            score = inter / len(shingles[a] | shingles[b])
            if score >= threshold:
                pairs.append({"a": candidates[a]["id"], "b": candidates[b]["id"], "score": round(score, 2)})
    pairs.sort(key=lambda p: -p["score"])
    return pairs, None


def build_inventory(paths, root, follow, threshold):
    root = root.resolve()
    queue = [p.resolve() for p in paths]
    files, units, refs = [], [], []
    seen = set()
    while queue:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        tag = f"F{len(files) + 1}"
        try:
            shown = str(path.relative_to(root))
        except ValueError:
            shown = str(path)
        files.append({
            "tag": tag,
            "path": shown,
            "bytes": len(data),
            "lines": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
            "sha256": hashlib.sha256(data).hexdigest(),
            "followed": len(files) >= len(paths),
        })
        for kind, line, heading, body in split_blocks(text.splitlines()):
            parts = [body] if kind in ("code", "frontmatter", "table") else sentences(body)
            for idx, sentence in enumerate(parts, 1):
                unit_id = f"{tag}-L{line}.{idx}"
                unit = {"id": unit_id, "file": tag, "line": line, "heading": heading,
                        "kind": kind, "text": sentence,
                        "flags": [] if kind == "code" else flags_for(sentence)}
                units.append(unit)
                if kind == "code":
                    continue
                for ref in refs_in(sentence, path.parent, root):
                    refs.append({"unit": unit_id, **ref})
                    target = Path(ref["resolved"]) if ref["resolved"] else None
                    if (follow and ref["status"] == "ok" and target and target.is_file()
                            and target.suffix.lower() in (".md", ".markdown")
                            and root in target.parents and path in [p.resolve() for p in paths]):
                        queue.append(target)
    dups, dup_note = near_duplicates(units, threshold)
    notes = [dup_note] if dup_note else []
    if len(units) > LARGE_INVENTORY:
        notes.append(f"清单有 {len(units)} 句，分路分析的读取成本已接近读全文；"
                     "建议只列出真正参与判断的文件，不用 --follow")
    counts = {}
    for unit in units:
        for flag in unit["flags"]:
            counts[flag] = counts.get(flag, 0) + 1
    return {
        "root": str(root),
        "files": files,
        "summary": {
            "units": len(units),
            "flag_counts": dict(sorted(counts.items())),
            "missing_refs": sum(1 for r in refs if r["status"] == "missing"),
            "near_duplicates": len(dups),
            "notes": notes,
        },
        "references": refs,
        "near_duplicates": dups,
        "units": units,
    }


def verify_findings(inv, lines):
    """按编号回原文核对子代理的发现：编号必须存在，引文去掉省略号后每段都要出现在所列句子里。"""
    units = {u["id"]: u["text"] for u in inv["units"]}
    problems, total, saw_none = [], 0, False
    for lineno, raw in enumerate(lines, 1):
        raw = raw.strip()
        if not raw:
            continue
        # 格式不对的行一律报错，不跳过：否则坏发现会悄悄绕过核对进入报告。
        if not raw.startswith("{"):
            problems.append({"line": lineno, "problem": "不是单行 JSON 对象"})
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append({"line": lineno, "problem": f"不是合法 JSON：{exc.msg}"})
            continue
        if item.get("none") is True:
            saw_none = True
            continue
        ids, quote = item.get("ids"), item.get("quote")
        if (not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids)
                or not isinstance(quote, str)):
            problems.append({"line": lineno, "problem": "缺少非空 ids 列表或字符串 quote"})
            continue
        total += 1
        unknown = [i for i in ids if i not in units]
        if unknown:
            problems.append({"line": lineno, "problem": f"编号不存在：{', '.join(map(str, unknown))}"})
            continue
        joined = normalize("".join(units[i] for i in ids))
        parts = [normalize(p) for p in ELLIPSIS.split(quote)]
        if not any(parts) or any(p and p not in joined for p in parts):
            problems.append({"line": lineno, "problem": "引文与所列编号的原句对不上"})
    if not total and not saw_none and not problems:
        problems.append({"line": 0, "problem": "既没有发现也没有 none 标记，可能是空文件或写错了文件"})
    return total, problems


def render_md(inv, flagged_only=False):
    out = ["# 提示词清单" + ("（仅带标记的句子）" if flagged_only else ""), ""]
    for f in inv["files"]:
        extra = "（跟随引用纳入）" if f["followed"] else ""
        out.append(f"- `{f['tag']}` {f['path']}{extra}：{f['lines']} 行，{f['bytes']} 字节，sha256 {f['sha256'][:12]}")
    s = inv["summary"]
    out += ["", "## 机械检查摘要", "",
            f"- 句子数：{s['units']}",
            f"- 标记计数：{', '.join(f'{k} {v}' for k, v in s['flag_counts'].items()) or '无'}",
            f"- 缺失引用：{s['missing_refs']}",
            f"- 近似重复对：{s['near_duplicates']}"]
    out += [f"- 说明：{note}" for note in s["notes"]]
    missing = [r for r in inv["references"] if r["status"] == "missing"]
    if missing:
        out += ["", "### 缺失引用", ""]
        out += [f"- `{r['unit']}` `{r['target']}`" for r in missing]
    if inv["near_duplicates"]:
        out += ["", "### 近似重复（3-gram Jaccard）", ""]
        out += [f"- `{p['a']}` ≈ `{p['b']}`（{p['score']}）" for p in inv["near_duplicates"]]
    out += ["", "## 句子", "", "标记：absolute 绝对化，unscoped_absolute 绝对化且无条件，gate 授权/确认/停下，review 审查，vague 模糊词。标记只是候选。"]
    current = None
    for unit in inv["units"]:
        if flagged_only and not unit["flags"]:
            continue
        key = (unit["file"], unit["heading"])
        if key != current:
            current = key
            out += ["", f"### {unit['file']} · {unit['heading'] or '（无标题）'}", ""]
        flag = f" [{','.join(unit['flags'])}]" if unit["flags"] else ""
        kind = "" if unit["kind"] in ("para", "list") else f" <{unit['kind']}>"
        body = unit["text"].replace("\n", "\n    ") if unit["kind"] == "code" else unit["text"]
        out.append(f"- `{unit['id']}`{kind}{flag} {body}")
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="提示词降噪：把提示词拆成编号句子清单并做机械检查（只读）。")
    parser.add_argument("files", nargs="+", type=Path, help="要分析的提示词文件")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="解析相对引用的仓库根目录，默认当前目录")
    parser.add_argument("--follow", action="store_true", help="把目标文件引用到的、root 内现存的 Markdown 一并纳入（一层）")
    parser.add_argument("--dup-threshold", type=float, default=0.5, help="近似重复阈值，默认 0.5")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--flagged-only", action="store_true", help="md 输出只保留带标记的句子，供只看措辞的分路使用")
    parser.add_argument("--out", type=Path, help="输出文件；不传则写 stdout")
    parser.add_argument("--verify", type=Path, metavar="FINDINGS", help="核对子代理发现文件（JSON 行）的编号与引文，不生成清单")
    args = parser.parse_args(argv)

    missing = [str(p) for p in args.files if not p.is_file()]
    if missing:
        print(f"文件不存在：{', '.join(missing)}", file=sys.stderr)
        return 2
    inv = build_inventory(args.files, args.root, args.follow, args.dup_threshold)
    if args.verify:
        total, problems = verify_findings(inv, args.verify.read_text(encoding="utf-8").splitlines())
        for p in problems:
            print(f"{args.verify}:{p['line']}: {p['problem']}")
        print(f"verified {total} findings, {len(problems)} problems")
        return 1 if problems else 0
    text = render_md(inv, args.flagged_only) if args.format == "md" else json.dumps(inv, ensure_ascii=False, indent=1) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        s = inv["summary"]
        print(f"wrote {args.out}: units={s['units']} missing_refs={s['missing_refs']} "
              f"near_duplicates={s['near_duplicates']} flags={s['flag_counts']}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
