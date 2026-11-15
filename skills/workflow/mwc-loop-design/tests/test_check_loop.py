import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_DIR / "scripts/check_loop.py"
FIXTURE_PATH = SKILL_DIR / "references/cpu-optimization.loop"


def load_checker():
    module_spec = importlib.util.spec_from_file_location("check_loop", SCRIPT_PATH)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError("cannot load check_loop.py")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


CHECKER = load_checker()


class LoopCheckerTests(unittest.TestCase):
    def setUp(self):
        self.source = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_valid_parallel_feedback_loop(self):
        result = CHECKER.parse_loop(self.source)
        data = CHECKER.result_dict(result)
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["cycles"], 1)
        self.assertEqual(data["summary"]["joins"], 1)
        self.assertEqual(data["errors"], [])

    def test_root_exit_is_required(self):
        result = CHECKER.parse_loop(self.source.replace("  exit when target_met;\n", "", 1))
        codes = {item.code for item in result.diagnostics if item.severity == "error"}
        self.assertIn("MISSING_LOOP_EXIT", codes)

    def test_empty_sources_are_rejected(self):
        for source in ("", " \t\n", "# empty loop\n"):
            with self.subTest(source=source):
                completed = subprocess.run(
                    [sys.executable, str(SCRIPT_PATH), "-", "--strict", "--format", "json"],
                    input=source, capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(completed.returncode, 1, completed.stderr)
                payload = json.loads(completed.stdout)
                self.assertFalse(payload["ok"])
                self.assertIn("EXPECTED_LOOP", {item["code"] for item in payload["errors"]})

    def test_invalid_condition_is_rejected(self):
        source = self.source.replace("  exit when target_met;\n", "  exit when target_met();\n", 1)
        result = CHECKER.parse_loop(source)
        codes = {item.code for item in result.diagnostics if item.severity == "error"}
        self.assertIn("INVALID_CONDITION", codes)

    def test_every_cycle_needs_a_local_exit_or_block(self):
        source = """\
loop spinning {
  goal "验证修复";
  entry work;
  exit when done;
  node work [kind=experiment] {
    does "反复尝试";
    emits result;
  }
  edge work -> work when retry;
}
"""
        result = CHECKER.parse_loop(source)
        codes = {item.code for item in result.diagnostics if item.severity == "error"}
        self.assertIn("CYCLE_NO_STOP", codes)

    def test_join_requires_matching_edges(self):
        source = self.source.replace("  edge experiment -> feedback when benchmark_updated;\n", "")
        result = CHECKER.parse_loop(source)
        codes = {item.code for item in result.diagnostics if item.severity == "error"}
        self.assertIn("JOIN_EDGE_MISSING", codes)

    def test_subcycles_cannot_borrow_stop_conditions(self):
        for extra_edges in (
            "  edge research -> research when retry;\n",
            "  edge research -> experiment when candidate_ready;\n"
            "  edge experiment -> research when retry;\n",
        ):
            with self.subTest(edges=extra_edges):
                source = self.source.replace("  join feedback", extra_edges + "  join feedback", 1)
                result = CHECKER.parse_loop(source)
                codes = {item.code for item in result.diagnostics if item.severity == "error"}
                self.assertIn("CYCLE_NO_STOP", codes)

    def test_self_loop_accepts_its_own_exit_or_block(self):
        for stop in ("exit when enough_evidence;", "block when no_signal;"):
            with self.subTest(stop=stop):
                source = self.source.replace(
                    "    emits hypotheses, research_notes;\n",
                    "    emits hypotheses, research_notes;\n    " + stop + "\n",
                    1,
                ).replace(
                    "  join feedback",
                    "  edge research -> research when retry;\n  join feedback",
                    1,
                )
                payload = CHECKER.result_dict(CHECKER.parse_loop(source))
                self.assertTrue(payload["ok"], payload["errors"])

    def test_tests_run_from_standalone_package(self):
        with tempfile.TemporaryDirectory(prefix="loop-checker-installed-") as directory:
            installed = Path(directory) / "installed/skills/mwc-loop-design"
            shutil.copytree(
                Path(__file__).resolve().parents[1], installed,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            completed = subprocess.run(
                [
                    sys.executable, str(installed / "tests/test_check_loop.py"),
                    "LoopCheckerTests.test_valid_parallel_feedback_loop",
                    "LoopCheckerTests.test_cli_json_output",
                ],
                cwd=directory, capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("Ran 2 tests", completed.stderr)

    def test_unreachable_node_is_rejected(self):
        source = self.source.replace(
            "  join feedback <- research, experiment, evaluate;\n",
            "  node unused [kind=wait] {\n"
            "    does \"没有连接的节点\";\n"
            "    emits nothing;\n"
            "  }\n\n"
            "  join feedback <- research, experiment, evaluate;\n",
        )
        result = CHECKER.parse_loop(source)
        codes = {item.code for item in result.diagnostics if item.severity == "error"}
        self.assertIn("UNREACHABLE_NODE", codes)

    def test_cli_json_output(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), str(FIXTURE_PATH), "--format", "json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["loop"], "cpu_optimize")


if __name__ == "__main__":
    unittest.main()
