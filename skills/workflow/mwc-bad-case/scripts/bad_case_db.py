#!/usr/bin/env python3
"""Small SQLite store for observed bad-case records.

The CLI stores observations and later analysis. It does not inspect chat history;
its caller supplies the evidence recovered from the host conversation store.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
STATUSES = ("open", "reviewing", "resolved", "ignored", "deleted")
JSON_FIELDS = ("context", "evidence", "analysis", "tags")
TEXT_FIELDS = (
    "title",
    "source",
    "session_id",
    "turn_ref",
    "occurred_at",
    "scene",
    "goal",
    "expected",
    "observed",
    "experience",
    "correction",
    "category",
)
SCALAR_FIELDS = TEXT_FIELDS + ("status", "severity", "confidence")
ALL_FIELDS = set(SCALAR_FIELDS) | set(JSON_FIELDS)
JSON_COLUMNS = {field: f"{field}_json" for field in JSON_FIELDS}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS bad_cases (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'reviewing', 'resolved', 'ignored', 'deleted')),
    source TEXT NOT NULL DEFAULT 'manual',
    session_id TEXT,
    turn_ref TEXT,
    occurred_at TEXT,
    scene TEXT,
    goal TEXT,
    expected TEXT,
    observed TEXT,
    experience TEXT,
    correction TEXT,
    category TEXT,
    severity INTEGER CHECK (severity IS NULL OR severity BETWEEN 1 AND 5),
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    context_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    analysis_json TEXT NOT NULL DEFAULT '{}',
    tags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bad_cases_status ON bad_cases(status);
CREATE INDEX IF NOT EXISTS idx_bad_cases_session ON bad_cases(session_id);
CREATE INDEX IF NOT EXISTS idx_bad_cases_occurred ON bad_cases(occurred_at);
CREATE INDEX IF NOT EXISTS idx_bad_cases_category ON bad_cases(category);

CREATE TABLE IF NOT EXISTS bad_case_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES bad_cases(id)
);

CREATE INDEX IF NOT EXISTS idx_bad_case_events_case
    ON bad_case_events(case_id, event_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_db_path() -> Path:
    configured = os.environ.get("MWC_BAD_CASE_DB")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "share" / "mwc-bad-case" / "bad-cases.sqlite3"


def resolve_db(value: str | None) -> Path:
    return Path(value).expanduser() if value else default_db_path()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current_version > SCHEMA_VERSION:
        connection.close()
        raise ValueError(
            f"database schema {current_version} is newer than supported {SCHEMA_VERSION}"
        )
    connection.executescript(SCHEMA_SQL)
    if current_version < SCHEMA_VERSION:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    return connection


def parse_json_value(raw: str, source: str) -> Any:
    if raw == "-":
        raw = sys.stdin.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source} is not valid JSON: {exc.msg}") from exc


def parse_json_document(raw: str, source: str) -> dict[str, Any]:
    value = parse_json_value(raw, source)
    if not isinstance(value, dict):
        raise ValueError(f"{source} must contain a JSON object")
    return value


def load_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args.json is not None and args.json_file is not None:
        raise ValueError("use only one of --json and --json-file")
    if args.json is not None:
        payload.update(parse_json_document(args.json, "--json"))
    if args.json_file is not None:
        payload.update(
            parse_json_document(
                Path(args.json_file).expanduser().read_text(encoding="utf-8"),
                "--json-file",
            )
        )

    for field in SCALAR_FIELDS:
        value = getattr(args, field, None)
        if value is not None:
            payload[field] = value
    for field in JSON_FIELDS:
        value = getattr(args, field, None)
        if value is not None:
            payload[field] = parse_json_value(value, f"--{field}")
    if "id" in payload and payload["id"] is None:
        payload.pop("id")
    return payload


def validate_payload(payload: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    unknown = sorted(set(payload) - (ALL_FIELDS | {"id"}))
    if unknown:
        raise ValueError(f"unsupported fields: {', '.join(unknown)}")
    result = dict(payload)
    if creating:
        result.setdefault("status", "open")
        result.setdefault("source", "manual")
        result.setdefault("context", {})
        result.setdefault("evidence", [])
        result.setdefault("analysis", {})
        result.setdefault("tags", [])
    if "title" in result and (not isinstance(result["title"], str) or not result["title"].strip()):
        raise ValueError("title must be a non-empty string")
    if creating and "title" not in result:
        raise ValueError("title is required")
    if "status" in result and result["status"] not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(STATUSES)}")
    if "severity" in result and result["severity"] is not None:
        try:
            result["severity"] = int(result["severity"])
        except (TypeError, ValueError) as exc:
            raise ValueError("severity must be an integer from 1 to 5") from exc
        if not 1 <= result["severity"] <= 5:
            raise ValueError("severity must be an integer from 1 to 5")
    if "confidence" in result and result["confidence"] is not None:
        try:
            result["confidence"] = float(result["confidence"])
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be a number from 0 to 1") from exc
        if not 0 <= result["confidence"] <= 1:
            raise ValueError("confidence must be a number from 0 to 1")
    for field in JSON_FIELDS:
        if field in result:
            try:
                json.dumps(result[field], ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field} must be JSON-serializable") from exc
    if "tags" in result:
        if not isinstance(result["tags"], list) or not all(
            isinstance(tag, str) and tag.strip() for tag in result["tags"]
        ):
            raise ValueError("tags must be a JSON array of non-empty strings")
    return result


def encode_value(field: str, value: Any) -> Any:
    if field in JSON_FIELDS:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def decode_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for field, column in JSON_COLUMNS.items():
        raw = result.pop(column)
        try:
            result[field] = json.loads(raw)
        except json.JSONDecodeError:
            result[field] = raw
    return result


def fetch_case(connection: sqlite3.Connection, case_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM bad_cases WHERE id = ?", (case_id,)).fetchone()
    return decode_row(row) if row else None


def append_event(
    connection: sqlite3.Connection,
    case_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO bad_case_events(case_id, event_type, occurred_at, payload_json)
        VALUES (?, ?, ?, ?)
        """,
        (case_id, event_type, utc_now(), json.dumps(payload, ensure_ascii=False, sort_keys=True)),
    )


def create_case(connection: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    payload = validate_payload(payload, creating=True)
    case_id = payload.pop("id", None) or f"bc-{uuid.uuid4().hex[:16]}"
    if not isinstance(case_id, str) or not case_id.startswith("bc-"):
        raise ValueError("id must start with 'bc-'")
    now = utc_now()
    payload["created_at"] = now
    payload["updated_at"] = now
    columns = ["id"] + list(SCALAR_FIELDS) + list(JSON_COLUMNS.values()) + ["created_at", "updated_at"]
    values: list[Any] = [case_id]
    for field in SCALAR_FIELDS:
        values.append(payload.get(field))
    for field in JSON_FIELDS:
        values.append(encode_value(field, payload[field]))
    values.extend([payload["created_at"], payload["updated_at"]])
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO bad_cases({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    append_event(connection, case_id, "create", {"record": {"id": case_id, **payload}})
    connection.commit()
    return fetch_case(connection, case_id)  # type: ignore[return-value]


def update_case(
    connection: sqlite3.Connection,
    case_id: str,
    payload: dict[str, Any],
    *,
    event_type: str = "update",
) -> dict[str, Any]:
    payload = validate_payload(payload, creating=False)
    payload.pop("id", None)
    if not payload:
        raise ValueError("at least one field is required for update")
    if fetch_case(connection, case_id) is None:
        raise ValueError(f"case not found: {case_id}")
    changes = []
    values: list[Any] = []
    for field, value in payload.items():
        column = JSON_COLUMNS.get(field, field)
        changes.append(f"{column} = ?")
        values.append(encode_value(field, value))
    now = utc_now()
    changes.append("updated_at = ?")
    values.extend([now, case_id])
    connection.execute(f"UPDATE bad_cases SET {', '.join(changes)} WHERE id = ?", values)
    append_event(connection, case_id, event_type, {"changes": payload})
    connection.commit()
    return fetch_case(connection, case_id)  # type: ignore[return-value]


def delete_case(
    connection: sqlite3.Connection, case_id: str, reason: str | None
) -> dict[str, Any]:
    if fetch_case(connection, case_id) is None:
        raise ValueError(f"case not found: {case_id}")
    now = utc_now()
    connection.execute(
        "UPDATE bad_cases SET status = 'deleted', updated_at = ? WHERE id = ?",
        (now, case_id),
    )
    append_event(connection, case_id, "delete", {"reason": reason or ""})
    connection.commit()
    return fetch_case(connection, case_id)  # type: ignore[return-value]


def list_cases(
    connection: sqlite3.Connection,
    *,
    status: str | None,
    category: str | None,
    session_id: str | None,
    text: str | None,
    tag: str | None,
    include_deleted: bool,
    limit: int,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    clauses = ["1 = 1"]
    params: list[Any] = []
    if not include_deleted:
        clauses.append("status != 'deleted'")
    if status and status != "all":
        if status not in STATUSES:
            raise ValueError(f"status must be one of: {', '.join(STATUSES)}, all")
        clauses.append("status = ?")
        params.append(status)
    elif not status and not include_deleted:
        clauses.append("status IN ('open', 'reviewing')")
    if category:
        clauses.append("category = ?")
        params.append(category)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if text:
        clauses.append(
            "(" + " OR ".join(f"{field} LIKE ?" for field in (
                "title", "scene", "goal", "expected", "observed", "experience", "correction", "analysis_json"
            )) + ")"
        )
        params.extend([f"%{text}%"] * 8)
    rows = connection.execute(
        f"SELECT * FROM bad_cases WHERE {' AND '.join(clauses)} "
        "ORDER BY COALESCE(occurred_at, created_at) DESC, created_at DESC",
        params,
    ).fetchall()
    records = [decode_row(row) for row in rows]
    if tag:
        records = [record for record in records if tag in record["tags"]]
    return records[:limit]


def case_history(connection: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT event_id, case_id, event_type, occurred_at, payload_json "
        "FROM bad_case_events WHERE case_id = ? ORDER BY event_id",
        (case_id,),
    ).fetchall()
    result = []
    for row in rows:
        event = dict(row)
        try:
            event["payload"] = json.loads(event.pop("payload_json"))
        except json.JSONDecodeError:
            event["payload"] = event.pop("payload_json")
        result.append(event)
    return result


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def print_records(records: list[dict[str, Any]], output_format: str) -> None:
    if output_format == "json":
        print_json(records)
        return
    if output_format == "jsonl":
        for record in records:
            print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return
    if output_format == "csv":
        fields = ["id", "title", "status", "source", "session_id", "category", "severity", "confidence", "occurred_at", "updated_at"]
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        return
    if not records:
        print("(no records)")
        return
    fields = ("id", "status", "category", "severity", "title")
    print("\t".join(fields))
    for record in records:
        print("\t".join(str(record.get(field) or "") for field in fields))


def add_payload_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", help="JSON object, or '-' to read it from stdin")
    parser.add_argument("--json-file", help="path to a JSON object")
    for field in SCALAR_FIELDS:
        parser.add_argument(f"--{field.replace('_', '-')}")
    for field in JSON_FIELDS:
        parser.add_argument(f"--{field}", help="JSON value")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        help="SQLite path; defaults to MWC_BAD_CASE_DB or ~/.local/share/mwc-bad-case/bad-cases.sqlite3",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="create the database and schema")

    create = commands.add_parser("create", aliases=["record"], help="create one bad-case record")
    add_payload_arguments(create)

    show = commands.add_parser("show", aliases=["get"], help="show one record")
    show.add_argument("id")
    show.add_argument("--history", action="store_true")

    listing = commands.add_parser("list", help="list open/reviewing records by default")
    listing.add_argument("--status", choices=(*STATUSES, "all"), help="explicit status, or all non-deleted records")
    listing.add_argument("--category")
    listing.add_argument("--session-id")
    listing.add_argument("--query")
    listing.add_argument("--tag")
    listing.add_argument("--include-deleted", action="store_true")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--format", choices=("table", "json", "jsonl", "csv"), default="table")

    update = commands.add_parser("update", help="update fields and append an event")
    update.add_argument("id")
    add_payload_arguments(update)

    delete = commands.add_parser("delete", help="soft-delete a record")
    delete.add_argument("id")
    delete.add_argument("--reason")

    restore = commands.add_parser("restore", help="restore a soft-deleted record")
    restore.add_argument("id")
    restore.add_argument("--status", choices=STATUSES[:-1], default="open")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = resolve_db(args.db)
    connection: sqlite3.Connection | None = None
    try:
        connection = connect(path)
        if args.command == "init":
            print_json({"db": str(path), "schema_version": SCHEMA_VERSION})
        elif args.command in ("create", "record"):
            print_json(create_case(connection, load_payload(args)))
        elif args.command in ("show", "get"):
            record = fetch_case(connection, args.id)
            if record is None:
                raise ValueError(f"case not found: {args.id}")
            if args.history:
                record["history"] = case_history(connection, args.id)
            print_json(record)
        elif args.command == "list":
            records = list_cases(
                connection,
                status=args.status,
                category=args.category,
                session_id=args.session_id,
                text=args.query,
                tag=args.tag,
                include_deleted=args.include_deleted,
                limit=args.limit,
            )
            print_records(records, args.format)
        elif args.command == "update":
            print_json(update_case(connection, args.id, load_payload(args)))
        elif args.command == "delete":
            print_json(delete_case(connection, args.id, args.reason))
        elif args.command == "restore":
            print_json(update_case(connection, args.id, {"status": args.status}, event_type="restore"))
        else:
            parser.error(f"unsupported command: {args.command}")
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if connection is not None:
            connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
