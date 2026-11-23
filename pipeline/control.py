"""Validate YAML flowcharts and advance local run state one event at a time."""

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

try:
    import yaml
except ModuleNotFoundError as exc:
    if exc.name != "yaml":
        raise
    sys.exit("pipeline: PyYAML is required; see pipeline/README.md")


IDENTIFIER = re.compile(r"[a-z][a-z0-9-]*")
PIPELINE_DIR = Path(__file__).resolve().parent
DEFINITION_FILE = "pipeline.yaml"
STATE_FILE = "state.json"
STATE_VERSION = 2
MAX_STEPS = 1000


@dataclass
class Node:
    instruction: str
    final: bool
    transitions: dict[str, str]


@dataclass
class Pipeline:
    id: str
    initial: str
    max_steps: int
    nodes: dict[str, Node]


class DefinitionLoader(yaml.BaseLoader):
    # Scalars stay text until the schema interprets them (including event names like on).
    def compose_node(self, parent, index):
        event = self.peek_event()
        if (
            getattr(event, "anchor", None) is not None
            or getattr(event, "tag", None) is not None
        ):
            raise ValueError("YAML anchors, aliases and explicit tags are not supported")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node, deep=deep)
        if len(mapping) != len(node.value):
            raise ValueError(f"duplicate YAML key near line {node.start_mark.line + 1}")
        return mapping


def identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {field}: {value!r}")
    return value


def layout_path(*parts: str) -> Path:
    path = PIPELINE_DIR
    for part in parts:
        path /= part
        if path.is_symlink():
            relative = path.relative_to(PIPELINE_DIR)
            raise ValueError(f"pipeline layout does not accept symlinks: {relative}")
    return path


def find_definition(name: str) -> Path:
    definitions = []
    for scope in ("pub", "pri"):
        path = layout_path(scope, name, DEFINITION_FILE)
        try:
            path.stat()
        except FileNotFoundError:
            continue
        definitions.append(path)
    if not definitions:
        raise ValueError(f"no pipeline definition for {name!r} under pub or pri")
    if len(definitions) != 1:
        raise ValueError(f"pipeline {name!r} has definitions in both pub and pri")
    return definitions[0]


def distances(start: list[str], edges: dict[str, list[str]]) -> dict[str, int]:
    result = dict.fromkeys(start, 0)
    queue = deque(start)
    while queue:
        source = queue.popleft()
        for target in edges[source]:
            if target not in result:
                result[target] = result[source] + 1
                queue.append(target)
    return result


def parse_definition(text: str) -> Pipeline:
    try:
        root = yaml.load(text, Loader=DefinitionLoader)
    except RecursionError:
        raise ValueError("YAML definition is nested too deeply") from None
    fields = {"version", "id", "initial", "max_steps", "steps"}
    if not isinstance(root, dict) or root.keys() != fields:
        expected = ", ".join(sorted(fields))
        raise ValueError(f"YAML definition requires exactly these keys: {expected}")
    if root["version"] != "1":
        raise ValueError("unsupported YAML definition version")
    name = identifier(root["id"], "pipeline id")
    initial = identifier(root["initial"], "initial step")
    limit = root["max_steps"]
    if (
        not isinstance(limit, str)
        or not re.fullmatch(r"[1-9][0-9]{0,3}", limit)
        or int(limit) > MAX_STEPS
    ):
        raise ValueError(f"max_steps must be a decimal integer from 1 to {MAX_STEPS}")
    max_steps = int(limit)

    steps = root["steps"]
    if not isinstance(steps, dict):
        raise ValueError("steps must be a mapping")
    nodes = {}
    for key, body in steps.items():
        node_id = identifier(key, "step id")
        if not isinstance(body, dict):
            raise ValueError(f"{node_id}: step must be a mapping")
        final = "final" in body
        if final:
            if body["final"] != "true" or body.keys() - {"final", "instruction"}:
                raise ValueError(f"{node_id}: final step only accepts final: true and an optional instruction")
        elif body.keys() != {"instruction", "events"}:
            raise ValueError(f"{node_id}: step needs an instruction and events")
        instruction = body.get("instruction", "")
        if not isinstance(instruction, str) or ("instruction" in body and not instruction.strip()):
            raise ValueError(f"{node_id}: instruction must contain plain text")
        transitions = {}
        if not final:
            events = body["events"]
            if not isinstance(events, dict) or not events:
                raise ValueError(f"{node_id}: events must be a non-empty mapping")
            for event, target in events.items():
                event_name = identifier(event, f"{node_id} event")
                transitions[event_name] = identifier(target, f"{node_id} target")
        nodes[node_id] = Node(instruction.strip(), final, transitions)

    if initial not in nodes or nodes[initial].final:
        raise ValueError("initial must refer to a step")
    successors = {node_id: list(node.transitions.values()) for node_id, node in nodes.items()}
    predecessors = {node_id: [] for node_id in nodes}
    for source, targets in successors.items():
        for target in targets:
            if target not in nodes:
                raise ValueError(f"{source}: unknown target {target}")
            predecessors[target].append(source)
    missing = nodes.keys() - distances([initial], successors).keys()
    if missing:
        raise ValueError(f"unreachable nodes: {', '.join(sorted(missing))}")
    to_exit = distances([node_id for node_id in nodes if nodes[node_id].final], predecessors)
    trapped = nodes.keys() - to_exit.keys()
    if trapped:
        raise ValueError(f"no path to a final from: {', '.join(sorted(trapped))}")
    if to_exit[initial] > max_steps:
        raise ValueError("max_steps is too small to reach any final")
    return Pipeline(name, initial, max_steps, nodes)


def definition_info(pipeline: Pipeline, text: str) -> dict:
    return {
        "pipeline": pipeline.id,
        "definition_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "max_steps": pipeline.max_steps,
    }


def node_info(node_id: str, node: Node) -> dict:
    return {"id": node_id, "final": node.final, "instruction": node.instruction, "events": node.transitions}


def load_run(run_dir: Path, name: str) -> tuple[dict, Pipeline, str]:
    state_path = run_dir / STATE_FILE
    if state_path.is_symlink():
        raise ValueError("run state must not be a symlink")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or type(state.get("version")) is not int:
        raise ValueError("unsupported run state format")
    if state["version"] == 1:
        raise ValueError("XML-era run; resume with the previous controller, or start a new YAML run")
    if state["version"] != STATE_VERSION:
        raise ValueError("unsupported run state format")
    text = state.get("definition")
    history = state.get("history")
    if not isinstance(text, str) or not isinstance(history, list):
        raise ValueError("invalid run state")
    pipeline = parse_definition(text)
    if pipeline.id != name:
        raise ValueError(f"run definition id {pipeline.id!r} does not match pipeline {name!r}")
    if len(history) > pipeline.max_steps:
        raise ValueError("run history exceeds max_steps")
    current = pipeline.initial
    for index, entry in enumerate(history, start=1):
        fields = ("event", "evidence", "recorded_at")
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(field), str) and entry[field].strip() for field in fields
        ):
            raise ValueError(f"invalid history entry {index}")
        target = pipeline.nodes[current].transitions.get(entry["event"])
        if target is None:
            raise ValueError(f"invalid transition in history entry {index}")
        current = target
    return state, pipeline, current


def run_info(
    state: dict,
    pipeline: Pipeline,
    current: str,
    history: bool = False,
    graph: bool = False,
) -> dict:
    node = pipeline.nodes[current]
    revision = len(state["history"])
    status = "running"
    if node.final:
        status = "finished"
    elif revision == pipeline.max_steps:
        status = "exhausted"
    current_info = node_info(current, node)
    if status != "running":
        current_info["events"] = {}
    result = {
        **definition_info(pipeline, state["definition"]),
        "status": status,
        "revision": revision,
        "current": current_info,
    }
    if history:
        result["history"] = state["history"]
    if graph:
        result["initial"] = pipeline.initial
        result["nodes"] = [
            node_info(node_id, node) for node_id, node in pipeline.nodes.items()
        ]
    return result


def save_run(run_dir: Path, state: dict) -> None:
    # Publish a complete snapshot so status can read without taking a lock.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=run_dir, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(state, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
            temporary.replace(run_dir / STATE_FILE)
        finally:
            temporary.unlink(missing_ok=True)


def advance(
    run_dir: Path, name: str, expected_revision: int, event: str, evidence: str
) -> dict:
    if not evidence.strip():
        raise ValueError("evidence must be non-empty")
    # Lock the directory, not the state file whose inode changes on each replace.
    directory = os.open(run_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        state, pipeline, current = load_run(run_dir, name)
        revision = len(state["history"])
        if revision != expected_revision:
            raise ValueError(f"revision mismatch: expected {expected_revision}, found {revision}; run status")
        node = pipeline.nodes[current]
        if node.final or revision == pipeline.max_steps:
            raise ValueError("run has stopped; cannot advance")
        target = node.transitions.get(event)
        if target is None:
            raise ValueError(f"event {event!r} is not available at {current}")
        state["history"].append({
            "event": event,
            "evidence": evidence.strip(),
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        save_run(run_dir, state)
        return run_info(state, pipeline, target)
    finally:
        os.close(directory)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="validate and print the YAML graph").add_argument("definition", type=Path)
    start = commands.add_parser("start", help="create a private run with a snapshot of the YAML")
    status = commands.add_parser("status", help="show the current node and available events")
    status.add_argument("--history", action="store_true")
    status.add_argument("--graph", action="store_true")
    move = commands.add_parser("advance", help="record an event and follow one transition")
    move.add_argument("--expect", type=int, required=True, metavar="REVISION")
    move.add_argument("--event", required=True)
    move.add_argument("--evidence", required=True)
    for command in (start, status, move):
        command.add_argument("name", metavar="NAME")
        command.add_argument("run_id", metavar="RUN_ID")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            text = args.definition.read_bytes().decode("utf-8")
            pipeline = parse_definition(text)
            result = {
                **definition_info(pipeline, text),
                "initial": pipeline.initial,
                "nodes": [node_info(node_id, node) for node_id, node in pipeline.nodes.items()],
            }
        else:
            name = identifier(args.name, "pipeline name")
            run_id = identifier(args.run_id, "run id")
            run_dir = layout_path("pri", name, "runs", run_id)
            if args.command == "start":
                text = find_definition(name).read_bytes().decode("utf-8")
                pipeline = parse_definition(text)
                if pipeline.id != name:
                    raise ValueError(f"definition id {pipeline.id!r} does not match pipeline {name!r}")
                run_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                run_dir.mkdir(mode=0o700)
                state = {"version": STATE_VERSION, "definition": text, "history": []}
                save_run(run_dir, state)
                result = run_info(state, pipeline, pipeline.initial)
            elif args.command == "status":
                state, pipeline, current = load_run(run_dir, name)
                result = run_info(state, pipeline, current, args.history, args.graph)
            else:
                result = advance(run_dir, name, args.expect, args.event, args.evidence)
            result["run_dir"] = str(run_dir)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"pipeline: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
