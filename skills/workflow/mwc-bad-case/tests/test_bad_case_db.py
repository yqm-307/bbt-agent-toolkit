"""Focused CLI checks for mwc-bad-case's SQLite store."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bad_case_db.py"


class BadCaseCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Path(self.temp_dir.name) / "bad-cases.sqlite3"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--db", str(self.db), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            self.fail(f"CLI failed ({result.returncode}): {result.stderr}")
        return result

    def test_record_update_history_soft_delete_and_restore(self) -> None:
        payload = {
            "title": "回答偏离用户想要的收尾",
            "source": "explicit",
            "session_id": "local-test-session",
            "turn_ref": "msg-17",
            "scene": "用户要求只记录问题，回答却开始给优化方案",
            "goal": "先留下 bad case",
            "expected": "只记录现场，不优化",
            "observed": "回答扩展成了优化建议",
            "experience": "不适，目标没有被尊重",
            "correction": "我现在不想做优化",
            "category": "scope-drift",
            "severity": 4,
            "confidence": 1,
            "context": {"model": "test", "skills": ["mwc-bad-case"]},
            "evidence": [{"role": "user", "ref": "msg-17", "quote": "我现在不想做优化"}],
            "analysis": {"stage": "observation", "hypotheses": [], "unknowns": []},
            "tags": ["scope", "user-correction"],
        }
        created = json.loads(self.run_cli("record", "--json", json.dumps(payload)).stdout)
        case_id = created["id"]
        self.assertEqual(created["status"], "open")
        self.assertEqual(created["evidence"][0]["ref"], "msg-17")

        updated = json.loads(
            self.run_cli(
                "update",
                case_id,
                "--status",
                "reviewing",
                "--analysis",
                json.dumps({"stage": "reviewing", "hypotheses": ["scope was widened"]}),
                "--evidence",
                json.dumps([{"role": "assistant", "ref": "msg-18", "quote": "建议现在优化"}]),
                "--tags",
                json.dumps(["scope", "updated"]),
            ).stdout
        )
        self.assertEqual(updated["status"], "reviewing")
        self.assertEqual(updated["analysis"]["stage"], "reviewing")
        self.assertEqual(updated["evidence"][0]["ref"], "msg-18")
        self.assertEqual(updated["tags"], ["scope", "updated"])

        with_history = json.loads(self.run_cli("show", case_id, "--history").stdout)
        self.assertEqual([event["event_type"] for event in with_history["history"]], ["create", "update"])

        listed = json.loads(self.run_cli("list", "--format", "json").stdout)
        self.assertEqual([record["id"] for record in listed], [case_id])
        filtered = json.loads(
            self.run_cli("list", "--query", "不适", "--format", "json").stdout
        )
        self.assertEqual(len(filtered), 1)

        deleted = json.loads(self.run_cli("delete", case_id, "--reason", "duplicate").stdout)
        self.assertEqual(deleted["status"], "deleted")
        self.assertEqual(json.loads(self.run_cli("list", "--format", "json").stdout), [])
        retained = json.loads(
            self.run_cli("list", "--include-deleted", "--format", "json").stdout
        )
        self.assertEqual(retained[0]["status"], "deleted")

        restored = json.loads(self.run_cli("restore", case_id).stdout)
        self.assertEqual(restored["status"], "open")
        history = json.loads(self.run_cli("show", case_id, "--history").stdout)["history"]
        self.assertEqual([event["event_type"] for event in history], ["create", "update", "delete", "restore"])

    def test_default_list_only_shows_active_cases(self) -> None:
        statuses = ("open", "reviewing", "resolved", "ignored", "deleted")
        for status in statuses:
            self.run_cli("record", "--title", status, "--status", status)

        def listed(*args: str) -> set[str]:
            records = json.loads(self.run_cli("list", *args, "--format", "json").stdout)
            return {record["status"] for record in records}

        self.assertEqual(listed(), {"open", "reviewing"})
        self.assertEqual(listed("--status", "all"), set(statuses) - {"deleted"})
        self.assertEqual(listed("--include-deleted"), set(statuses))
        self.assertEqual(listed("--status", "all", "--include-deleted"), set(statuses))
        for status in statuses[:-1]:
            self.assertEqual(listed("--status", status), {status})
        self.assertEqual(listed("--status", "deleted"), set())
        self.assertEqual(listed("--status", "deleted", "--include-deleted"), {"deleted"})
        self.assertEqual(listed("--query", "ignored"), set())
        self.assertEqual(listed("--status", "all", "--query", "ignored"), {"ignored"})

    def test_invalid_payload_fails_without_creating_record(self) -> None:
        result = self.run_cli("record", "--title", "", check=False)
        self.assertNotEqual(result.returncode, 0)
        listed = json.loads(self.run_cli("list", "--format", "json").stdout)
        self.assertEqual(listed, [])


if __name__ == "__main__":
    unittest.main()
