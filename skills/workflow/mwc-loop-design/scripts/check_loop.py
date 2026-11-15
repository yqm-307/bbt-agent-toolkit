#!/usr/bin/env python3
"""静态检查不可执行的 Loop DSL 描述。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

IDENT = r"[A-Za-z_][A-Za-z0-9_-]*"
IDENT_RE = re.compile(r"^" + IDENT + r"$")
CONDITION_RE = re.compile(
    r"^(?:not\s+)?"
    + IDENT
    + r"(?:\s+(?:and|or)\s+(?:not\s+)?"
    + IDENT
    + r")*$"
)
STRING_RE = re.compile(r'^(?:goal|invariant|does)\s+("(?:\\.|[^"\\])*")\s*;$')
NODE_RE = re.compile(
    r"^node\s+(" + IDENT + r")(?:\s+\[([^\]]*)\])?\s*\{$"
)
LOOP_RE = re.compile(r"^loop\s+(" + IDENT + r")\s*\{$")
EDGE_RE = re.compile(
    r"^edge\s+(" + IDENT + r")\s*->\s+(" + IDENT + r")\s+when\s+(.+?)\s*;$"
)
JOIN_RE = re.compile(r"^join\s+(" + IDENT + r")\s*<-\s+(.+?)\s*;$")
ENTRY_RE = re.compile(r"^entry\s+(.+?)\s*;$")
WHEN_RE = re.compile(r"^(exit|block)\s+when\s+(.+?)\s*;$")
LIST_RE = re.compile(r"^(reads|emits)\s+(.+?)\s*;$")

VALID_KINDS = {"discover", "experiment", "observe", "judge", "act", "wait", "gate"}
VALID_RUN_MODES = {"serial", "parallel", "gate"}


@dataclass
class Diagnostic:
    severity: str
    code: str
    line: int
    message: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "line": self.line,
            "message": self.message,
        }


@dataclass
class Node:
    name: str
    line: int
    attrs: Dict[str, str] = field(default_factory=dict)
    does: Optional[str] = None
    reads: List[str] = field(default_factory=list)
    emits: List[str] = field(default_factory=list)
    exits: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)

    @property
    def kind(self) -> Optional[str]:
        return self.attrs.get("kind")

    @property
    def run(self) -> str:
        return self.attrs.get("run", "serial")


@dataclass
class Edge:
    source: str
    target: str
    condition: str
    line: int


@dataclass
class Join:
    target: str
    sources: List[str]
    line: int


@dataclass
class LoopSpec:
    name: str
    line: int
    goal: Optional[str] = None
    invariants: List[str] = field(default_factory=list)
    entries: List[str] = field(default_factory=list)
    exits: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)
    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    joins: List[Join] = field(default_factory=list)


@dataclass
class ParseResult:
    spec: Optional[LoopSpec]
    diagnostics: List[Diagnostic]


def add_diagnostic(
    diagnostics: List[Diagnostic], severity: str, code: str, line: int, message: str
) -> None:
    diagnostics.append(Diagnostic(severity, code, line, message))


def strip_comment(raw: str) -> str:
    """删除字符串外的 # 注释，保留字符串中的 #。"""
    in_string = False
    escaped = False
    for index, char in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if char == "#" and not in_string:
            return raw[:index]
    return raw


def parse_string(token: str, line: int, diagnostics: List[Diagnostic]) -> Optional[str]:
    try:
        value = json.loads(token)
    except json.JSONDecodeError:
        add_diagnostic(diagnostics, "error", "INVALID_STRING", line, "字符串必须是 JSON 风格的双引号文本")
        return None
    if not isinstance(value, str):
        add_diagnostic(diagnostics, "error", "INVALID_STRING", line, "这里需要字符串")
        return None
    if not value.strip():
        add_diagnostic(diagnostics, "error", "EMPTY_STRING", line, "字符串不能为空")
        return None
    return value


def parse_identifier_list(raw: str) -> Optional[List[str]]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values or any(IDENT_RE.fullmatch(item) is None for item in values):
        return None
    return values


def parse_condition(raw: str, line: int, diagnostics: List[Diagnostic]) -> Optional[str]:
    condition = raw.strip()
    if not condition or CONDITION_RE.fullmatch(condition) is None:
        add_diagnostic(
            diagnostics,
            "error",
            "INVALID_CONDITION",
            line,
            "条件只能由标识符和 and/or/not 组成，例如 target_met or blocked",
        )
        return None
    return condition


def parse_attrs(raw: Optional[str], line: int, diagnostics: List[Diagnostic]) -> Dict[str, str]:
    if raw is None or not raw.strip():
        return {}
    attrs: Dict[str, str] = {}
    for item in raw.split(","):
        pair = item.strip().split("=", 1)
        if len(pair) != 2 or not IDENT_RE.fullmatch(pair[0].strip()):
            add_diagnostic(diagnostics, "error", "INVALID_ATTRIBUTE", line, "节点属性必须写成 key=value")
            continue
        key, value = pair[0].strip(), pair[1].strip()
        if key in attrs:
            add_diagnostic(diagnostics, "error", "DUPLICATE_ATTRIBUTE", line, f"重复节点属性：{key}")
        attrs[key] = value
    if "mode" in attrs:
        if "run" in attrs:
            add_diagnostic(diagnostics, "error", "DUPLICATE_RUN_MODE", line, "同时使用 mode 和 run")
        else:
            attrs["run"] = attrs.pop("mode")
    unknown = sorted(set(attrs) - {"kind", "run"})
    for key in unknown:
        add_diagnostic(diagnostics, "error", "UNKNOWN_ATTRIBUTE", line, f"未知节点属性：{key}")
    return attrs


def parse_loop(source: str) -> ParseResult:
    diagnostics: List[Diagnostic] = []
    spec: Optional[LoopSpec] = None
    current_node: Optional[Node] = None
    started = False
    closed = False

    for line_number, raw in enumerate(source.splitlines(), start=1):
        line = strip_comment(raw).strip()
        if not line:
            continue

        if not started:
            match = LOOP_RE.fullmatch(line)
            if match is None:
                add_diagnostic(diagnostics, "error", "EXPECTED_LOOP", line_number, "文件第一条语句必须是 loop NAME {")
                continue
            spec = LoopSpec(name=match.group(1), line=line_number)
            started = True
            continue

        if current_node is not None:
            if line == "}":
                if current_node.name not in spec.nodes:  # type: ignore[union-attr]
                    spec.nodes[current_node.name] = current_node  # type: ignore[union-attr]
                current_node = None
                continue
            parse_node_statement(current_node, line, line_number, diagnostics)
            continue

        if closed:
            add_diagnostic(diagnostics, "error", "TRAILING_STATEMENT", line_number, "loop 结束后不能再有语句")
            continue

        if line == "}":
            closed = True
            continue

        node_match = NODE_RE.fullmatch(line)
        if node_match is not None:
            assert spec is not None
            name = node_match.group(1)
            if name in spec.nodes:
                add_diagnostic(diagnostics, "error", "DUPLICATE_NODE", line_number, f"重复节点：{name}")
            current_node = Node(
                name=name,
                line=line_number,
                attrs=parse_attrs(node_match.group(2), line_number, diagnostics),
            )
            continue

        assert spec is not None
        parse_root_statement(spec, line, line_number, diagnostics)

    if not started:
        if not diagnostics:
            add_diagnostic(diagnostics, "error", "EXPECTED_LOOP", 1, "文件必须包含 loop NAME { 声明")
        return ParseResult(None, diagnostics)
    assert spec is not None
    if current_node is not None:
        add_diagnostic(diagnostics, "error", "UNCLOSED_NODE", current_node.line, f"节点未闭合：{current_node.name}")
        if current_node.name not in spec.nodes:
            spec.nodes[current_node.name] = current_node
    if not closed:
        add_diagnostic(diagnostics, "error", "UNCLOSED_LOOP", spec.line, f"loop 未闭合：{spec.name}")
    validate_spec(spec, diagnostics)
    return ParseResult(spec, diagnostics)


def parse_root_statement(
    spec: LoopSpec, line: str, line_number: int, diagnostics: List[Diagnostic]
) -> None:
    text_match = STRING_RE.fullmatch(line)
    if text_match is not None:
        keyword = line.split(None, 1)[0]
        if keyword not in {"goal", "invariant"}:
            add_diagnostic(diagnostics, "error", "INVALID_ROOT_STATEMENT", line_number, f"loop 内不支持：{keyword}")
            return
        value = parse_string(text_match.group(1), line_number, diagnostics)
        if value is None:
            return
        if keyword == "goal":
            if spec.goal is not None:
                add_diagnostic(diagnostics, "error", "DUPLICATE_GOAL", line_number, "goal 只能声明一次")
            spec.goal = value
        else:
            spec.invariants.append(value)
        return

    entry_match = ENTRY_RE.fullmatch(line)
    if entry_match is not None:
        values = parse_identifier_list(entry_match.group(1))
        if values is None:
            add_diagnostic(diagnostics, "error", "INVALID_ENTRY", line_number, "entry 后需要一个或多个节点名")
        else:
            spec.entries.extend(values)
        return

    when_match = WHEN_RE.fullmatch(line)
    if when_match is not None:
        condition = parse_condition(when_match.group(2), line_number, diagnostics)
        if condition is not None:
            if when_match.group(1) == "exit":
                spec.exits.append(condition)
            else:
                spec.blocks.append(condition)
        return

    edge_match = EDGE_RE.fullmatch(line)
    if edge_match is not None:
        condition = parse_condition(edge_match.group(3), line_number, diagnostics)
        if condition is not None:
            spec.edges.append(Edge(edge_match.group(1), edge_match.group(2), condition, line_number))
        return

    join_match = JOIN_RE.fullmatch(line)
    if join_match is not None:
        sources = parse_identifier_list(join_match.group(2))
        if sources is None:
            add_diagnostic(diagnostics, "error", "INVALID_JOIN", line_number, "join 来源需要逗号分隔的节点名")
        else:
            spec.joins.append(Join(join_match.group(1), sources, line_number))
        return

    add_diagnostic(diagnostics, "error", "UNKNOWN_STATEMENT", line_number, f"无法识别的语句：{line}")


def parse_node_statement(
    node: Node, line: str, line_number: int, diagnostics: List[Diagnostic]
) -> None:
    text_match = STRING_RE.fullmatch(line)
    if text_match is not None:
        keyword = line.split(None, 1)[0]
        if keyword != "does":
            add_diagnostic(diagnostics, "error", "INVALID_NODE_STATEMENT", line_number, f"节点内不支持：{keyword}")
            return
        value = parse_string(text_match.group(1), line_number, diagnostics)
        if value is not None:
            if node.does is not None:
                add_diagnostic(diagnostics, "error", "DUPLICATE_DOES", line_number, "每个节点只能声明一次 does")
            node.does = value
        return

    list_match = LIST_RE.fullmatch(line)
    if list_match is not None:
        values = parse_identifier_list(list_match.group(2))
        if values is None:
            add_diagnostic(diagnostics, "error", "INVALID_DATA_LIST", line_number, "reads/emits 后需要逗号分隔的标识符")
        elif list_match.group(1) == "reads":
            node.reads.extend(values)
        else:
            node.emits.extend(values)
        return

    when_match = WHEN_RE.fullmatch(line)
    if when_match is not None:
        condition = parse_condition(when_match.group(2), line_number, diagnostics)
        if condition is not None:
            if when_match.group(1) == "exit":
                node.exits.append(condition)
            else:
                node.blocks.append(condition)
        return

    add_diagnostic(diagnostics, "error", "UNKNOWN_NODE_STATEMENT", line_number, f"无法识别的节点语句：{line}")


def adjacency(spec: LoopSpec) -> Dict[str, List[str]]:
    result = {name: [] for name in spec.nodes}
    for edge in spec.edges:
        if edge.source in result and edge.target in result:
            result[edge.source].append(edge.target)
    return result


def strongly_connected_components(spec: LoopSpec) -> List[List[str]]:
    graph = adjacency(spec)
    index = 0
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    stack: List[str] = []
    on_stack = set()
    components: List[List[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for target in graph[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] == indices[node]:
            component: List[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node:
                    break
            components.append(component)

    for node in graph:
        if node not in indices:
            visit(node)
    return components


def reachable_nodes(spec: LoopSpec) -> set:
    graph = adjacency(spec)
    seen = set()
    pending = list(spec.entries)
    while pending:
        current = pending.pop()
        if current in seen or current not in graph:
            continue
        seen.add(current)
        pending.extend(graph[current])
    return seen


def validate_spec(spec: LoopSpec, diagnostics: List[Diagnostic]) -> None:
    if spec.goal is None:
        add_diagnostic(diagnostics, "error", "MISSING_GOAL", spec.line, "loop 必须声明 goal")
    if not spec.exits:
        add_diagnostic(diagnostics, "error", "MISSING_LOOP_EXIT", spec.line, "loop 必须至少声明一个 exit when 条件")
    if not spec.entries:
        add_diagnostic(diagnostics, "error", "MISSING_ENTRY", spec.line, "loop 必须声明 entry")
    if not spec.nodes:
        add_diagnostic(diagnostics, "error", "MISSING_NODE", spec.line, "loop 至少需要一个 node")
        return

    for node in spec.nodes.values():
        if node.kind is None:
            add_diagnostic(diagnostics, "error", "MISSING_NODE_KIND", node.line, f"节点缺少 kind：{node.name}")
        elif node.kind not in VALID_KINDS:
            add_diagnostic(diagnostics, "error", "INVALID_NODE_KIND", node.line, f"未知节点 kind：{node.kind}")
        if node.run not in VALID_RUN_MODES:
            add_diagnostic(diagnostics, "error", "INVALID_RUN_MODE", node.line, f"未知运行模式：{node.run}")
        if node.does is None:
            add_diagnostic(diagnostics, "error", "MISSING_DOES", node.line, f"节点缺少 does：{node.name}")
        if not node.emits:
            add_diagnostic(diagnostics, "warning", "MISSING_EMITS", node.line, f"节点没有声明 emits：{node.name}")

    for entry in spec.entries:
        if entry not in spec.nodes:
            add_diagnostic(diagnostics, "error", "UNKNOWN_ENTRY", spec.line, f"entry 引用了不存在的节点：{entry}")

    edge_pairs = {(edge.source, edge.target) for edge in spec.edges}
    for edge in spec.edges:
        if edge.source not in spec.nodes:
            add_diagnostic(diagnostics, "error", "UNKNOWN_EDGE_SOURCE", edge.line, f"边的起点不存在：{edge.source}")
        if edge.target not in spec.nodes:
            add_diagnostic(diagnostics, "error", "UNKNOWN_EDGE_TARGET", edge.line, f"边的终点不存在：{edge.target}")

    for join in spec.joins:
        if join.target not in spec.nodes:
            add_diagnostic(diagnostics, "error", "UNKNOWN_JOIN_TARGET", join.line, f"join 目标不存在：{join.target}")
        for source in join.sources:
            if source not in spec.nodes:
                add_diagnostic(diagnostics, "error", "UNKNOWN_JOIN_SOURCE", join.line, f"join 来源不存在：{source}")
            elif (source, join.target) not in edge_pairs:
                add_diagnostic(
                    diagnostics,
                    "error",
                    "JOIN_EDGE_MISSING",
                    join.line,
                    f"join {join.target} 缺少 {source} -> {join.target} 边",
                )

    reachable = reachable_nodes(spec)
    for node_name, node in spec.nodes.items():
        if node_name not in reachable:
            add_diagnostic(diagnostics, "error", "UNREACHABLE_NODE", node.line, f"节点从 entry 不可达：{node_name}")

    components = strongly_connected_components(spec)
    cycles: List[List[str]] = []
    graph = adjacency(spec)
    for component in components:
        if len(component) > 1 or any(node in graph[node] for node in component):
            cycles.append(component)

    # 删除停止节点后仍有环，说明存在绕过所有局部 exit/block 的路径。
    stop_free_spec = replace(
        spec,
        nodes={name: node for name, node in spec.nodes.items() if not (node.exits or node.blocks)},
    )
    stop_free_graph = adjacency(stop_free_spec)
    for component in strongly_connected_components(stop_free_spec):
        if len(component) > 1 or any(node in stop_free_graph[node] for node in component):
            add_diagnostic(
                diagnostics,
                "error",
                "CYCLE_NO_STOP",
                min(spec.nodes[node].line for node in component),
                "循环环路必须在环内声明 exit when 或 block when",
            )

    if not cycles:
        add_diagnostic(diagnostics, "warning", "NO_CYCLE", spec.line, "当前图没有回边，描述的是一次性流程而非循环")
    if not spec.invariants:
        add_diagnostic(diagnostics, "warning", "NO_INVARIANT", spec.line, "建议声明 invariant，避免优化目标改变时破坏既有标准")
    if not spec.blocks and not any(node.blocks for node in spec.nodes.values()):
        add_diagnostic(diagnostics, "warning", "NO_BLOCK_CONDITION", spec.line, "建议声明 block when，用于无反馈、资源耗尽或权限不足时暂停")
    if not any(node.kind in {"judge", "observe"} for node in spec.nodes.values()):
        add_diagnostic(diagnostics, "warning", "NO_FEEDBACK_NODE", spec.line, "建议至少有一个 judge 或 observe 节点产生反馈")

    parallel_nodes = [node for node in spec.nodes.values() if node.run == "parallel"]
    if len(parallel_nodes) > 1 and not spec.joins:
        add_diagnostic(
            diagnostics,
            "warning",
            "PARALLEL_WITHOUT_JOIN",
            parallel_nodes[0].line,
            "存在多个 parallel 节点但没有 join，难以表达并发结果如何汇合",
        )


def result_dict(result: ParseResult) -> Dict[str, Any]:
    errors = [item.as_dict() for item in result.diagnostics if item.severity == "error"]
    warnings = [item.as_dict() for item in result.diagnostics if item.severity == "warning"]
    spec = result.spec
    cycle_count = 0
    if spec is not None:
        graph = adjacency(spec)
        for component in strongly_connected_components(spec):
            if len(component) > 1 or any(node in graph[node] for node in component):
                cycle_count += 1
    summary: Dict[str, object] = {
        "loop": spec.name if spec else None,
        "nodes": len(spec.nodes) if spec else 0,
        "edges": len(spec.edges) if spec else 0,
        "joins": len(spec.joins) if spec else 0,
        "cycles": cycle_count,
    }
    return {"ok": not errors, "summary": summary, "errors": errors, "warnings": warnings}


def format_text(result: ParseResult) -> str:
    data = result_dict(result)
    summary = data["summary"]
    status = "PASS" if data["ok"] else "FAIL"
    lines = [
        f"{status}: loop={summary['loop']} nodes={summary['nodes']} edges={summary['edges']} joins={summary['joins']}"
    ]
    for item in data["errors"] + data["warnings"]:
        lines.append(f"{item['severity'].upper()} [{item['code']}] line {item['line']}: {item['message']}")
    return "\n".join(lines)


def load_source(path: str) -> Tuple[str, Optional[str]]:
    if path == "-":
        return sys.stdin.read(), None
    source_path = Path(path)
    try:
        return source_path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError) as exc:
        return "", str(exc)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="检查不可执行的 Loop DSL 语法、图结构和退出条件")
    parser.add_argument("path", help=".loop 文件路径，使用 - 从 stdin 读取")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--strict", action="store_true", help="把 warning 也作为失败返回")
    args = parser.parse_args(argv)

    source, error = load_source(args.path)
    if error is not None:
        print(f"ERROR: cannot read {args.path}: {error}", file=sys.stderr)
        return 2
    result = parse_loop(source)
    if args.format == "json":
        print(json.dumps(result_dict(result), ensure_ascii=False, indent=2))
    else:
        print(format_text(result))
    has_errors = any(item.severity == "error" for item in result.diagnostics)
    has_warnings = any(item.severity == "warning" for item in result.diagnostics)
    return 1 if has_errors or (args.strict and has_warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
