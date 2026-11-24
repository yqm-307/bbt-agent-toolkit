"""YAML Pipeline v1 的最小离线 CLI 行为回归。

契约来源是 pipeline/README.md。每个用例把控制脚本复制到临时工具箱的
pipeline/ 中，只通过真实进程验证 pub/pri 布局与运行命令，只使用合成证据，
不读写仓库自己的 pipeline/pub 或 pipeline/pri。
"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PIPELINE_DIR = Path(__file__).resolve().parents[1]
CONTROL_SOURCE = PIPELINE_DIR / "control.py"
PYTHON = sys.executable

ADMISSION_YAML = """version: 1
id: prompt-admission
initial: screen
max_steps: 16
steps:
  screen:
    instruction: 筛查材料；候选卡准备好后交人审。
    events:
      prepared: review
  review:
    instruction: 人工审阅；可要求修订后重审，接受后进入观察。
    events:
      revise: screen
      accepted: monitor
  monitor:
    instruction: 观察留痕；样本足够后交人工判断，也可继续留痕。
    events:
      sampled: monitor
      ready: approve
  approve:
    instruction: 人工批准，或退回继续观察。
    events:
      approved: admitted
      hold: monitor
  admitted:
    final: true
    instruction: 已准入。
"""

LOOP_YAML = """version: 1
id: loop-budget
initial: wait
max_steps: 3
steps:
  wait:
    instruction: 等待外部结果；可留痕或结束。
    events:
      stay: wait
      done: finish
  finish:
    final: true
"""

NO_EXIT_YAML = """version: 1
id: no-exit
initial: a
max_steps: 3
steps:
  a:
    instruction: 甲。
    events:
      next: b
  b:
    instruction: 乙。
    events:
      back: a
"""

UNKNOWN_TARGET_YAML = """version: 1
id: unknown-target
initial: a
max_steps: 2
steps:
  a:
    instruction: 甲。
    events:
      go: missing
  done:
    final: true
"""

REPLACEMENT_YAML = """version: 1
id: replacement
initial: only
max_steps: 1
steps:
  only:
    instruction: 替换定义。
    events:
      finish: done
  done:
    final: true
"""

DUPLICATE_EVENT_YAML = """version: 1
id: duplicate-event
initial: a
max_steps: 2
steps:
  a:
    instruction: 甲。
    events:
      go: b
      go: c
  b:
    final: true
  c:
    final: true
"""

ANCHOR_YAML = """version: 1
id: anchor
initial: a
max_steps: 1
steps:
  a:
    instruction: 甲。
    events:
      go: &target done
  done:
    final: true
"""

TAG_YAML = """version: 1
id: tag
initial: a
max_steps: 1
steps:
  a:
    instruction: 甲。
    events:
      go: !!str done
  done:
    final: true
"""


def single_step(pipeline_id):
    return f"""version: 1
id: {pipeline_id}
initial: only
max_steps: 1
steps:
  only:
    instruction: 合成：一步结束。
    events:
      finish: done
  done:
    final: true
"""


class PipelineCliTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.toolkit = self.root / "toolkit"
        self.pipeline = self.toolkit / "pipeline"
        self.pipeline.mkdir(parents=True)
        self.control = self.pipeline / "control.py"
        self.control.write_bytes(CONTROL_SOURCE.read_bytes())
        self.pub = self.pipeline / "pub"
        self.pri = self.pipeline / "pri"
        self.pub.mkdir()
        self.pri.mkdir()

    def run_cli(self, *args, cwd=None):
        return subprocess.run(
            [PYTHON, "-B", str(self.control), *map(str, args)],
            cwd=str(cwd or self.root),
            text=True,
            capture_output=True,
            check=False,
        )

    def ok_json(self, *args, cwd=None):
        result = self.run_cli(*args, cwd=cwd)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def failed(self, *args, cwd=None):
        result = self.run_cli(*args, cwd=cwd)
        self.assertEqual(
            result.returncode, 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.startswith("pipeline: "), result.stderr)
        return result.stderr

    def write_definition(self, name, body, scope="pub"):
        directory = self.pipeline / scope / name
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "pipeline.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def run_dir(self, name, run_id):
        return self.pipeline / "pri" / name / "runs" / run_id

    def start_admission(self, run_id="run", cwd=None):
        self.write_definition("prompt-admission", ADMISSION_YAML)
        started = self.ok_json("start", "prompt-admission", run_id, cwd=cwd)
        run = self.run_dir("prompt-admission", run_id)
        self.assertEqual(started["run_dir"], str(run))
        self.assertTrue(Path(started["run_dir"]).is_absolute())
        return run, started

    def pub_entries(self):
        return sorted(path.relative_to(self.pub).as_posix() for path in self.pub.rglob("*"))

    def test_prompt_admission_round_trip_reaches_final_and_stops(self):
        """筛查→人审→回环→观察自环→人工批准→终点，结束后拒绝推进。"""
        run, started = self.start_admission(cwd=self.root)
        self.assertEqual(started["pipeline"], "prompt-admission")
        self.assertEqual(started["status"], "running")
        self.assertEqual(started["revision"], 0)
        self.assertEqual(started["current"]["id"], "screen")
        self.assertEqual(started["max_steps"], 16)
        self.assertEqual(
            started["definition_sha256"],
            hashlib.sha256(ADMISSION_YAML.encode("utf-8")).hexdigest(),
        )

        steps = [
            ("prepared", "合成：候选卡 DEMO-1 已准备", "review"),
            ("revise", "合成：审阅要求补反例", "screen"),
            ("prepared", "合成：按反馈修订候选卡", "review"),
            ("accepted", "合成：人审接受", "monitor"),
            ("sampled", "合成：观测样本已留痕", "monitor"),
            ("ready", "合成：观测足以交人工判断", "approve"),
            ("approved", "合成：人工批准准入", "admitted"),
        ]
        for revision, (event, evidence, target) in enumerate(steps):
            result = self.ok_json(
                "advance",
                "prompt-admission",
                "run",
                "--expect",
                revision,
                "--event",
                event,
                "--evidence",
                evidence,
                cwd=self.toolkit,
            )
            self.assertEqual(result["run_dir"], str(run))
            self.assertEqual(result["revision"], revision + 1)
            self.assertEqual(result["current"]["id"], target)
            self.assertNotIn("history", result)

        status = self.ok_json(
            "status", "prompt-admission", "run", "--history", cwd=self.pri
        )
        self.assertEqual(status["run_dir"], str(run))
        self.assertEqual(status["status"], "finished")
        self.assertEqual(status["revision"], len(steps))
        self.assertEqual(status["current"]["id"], "admitted")
        self.assertTrue(status["current"]["final"])
        self.assertEqual(status["current"]["events"], {})
        self.assertEqual([entry["event"] for entry in status["history"]], [s[0] for s in steps])
        self.assertEqual(
            [entry["evidence"] for entry in status["history"]], [s[1] for s in steps]
        )
        self.assertEqual(set(status["history"][0]), {"event", "evidence", "recorded_at"})

        before = (run / "state.json").read_bytes()
        stderr = self.failed(
            "advance",
            "prompt-admission",
            "run",
            "--expect",
            len(steps),
            "--event",
            "approved",
            "--evidence",
            "合成：结束后重试",
        )
        self.assertIn("run has stopped", stderr)
        self.assertEqual((run / "state.json").read_bytes(), before)
        self.assertEqual(
            self.pub_entries(),
            ["prompt-admission", "prompt-admission/pipeline.yaml"],
        )

    def test_max_steps_exhausts_loop_and_freezes_history(self):
        """自环消耗预算；用满 max_steps 停在 exhausted，之后不能再推进。"""
        self.write_definition("loop-budget", LOOP_YAML)
        run = self.run_dir("loop-budget", "loop-run")
        started = self.ok_json("start", "loop-budget", "loop-run")
        self.assertEqual(started["run_dir"], str(run))
        self.assertEqual((started["status"], started["current"]["id"]), ("running", "wait"))

        for revision in range(3):
            result = self.ok_json(
                "advance",
                "loop-budget",
                "loop-run",
                "--expect",
                revision,
                "--event",
                "stay",
                "--evidence",
                f"合成：第 {revision + 1} 次留痕",
            )
            self.assertEqual(result["revision"], revision + 1)
            self.assertEqual(result["current"]["id"], "wait")

        status = self.ok_json("status", "loop-budget", "loop-run", "--history")
        self.assertEqual(status["status"], "exhausted")
        self.assertEqual(status["revision"], 3)
        self.assertEqual(status["current"]["id"], "wait")
        self.assertEqual(status["current"]["events"], {})
        self.assertEqual([entry["event"] for entry in status["history"]], ["stay"] * 3)

        before = (run / "state.json").read_bytes()
        stderr = self.failed(
            "advance",
            "loop-budget",
            "loop-run",
            "--expect",
            3,
            "--event",
            "done",
            "--evidence",
            "合成：预算用尽后重试",
        )
        self.assertIn("run has stopped", stderr)
        self.assertEqual((run / "state.json").read_bytes(), before)

    def test_invalid_event_and_stale_revision_leave_history_unchanged(self):
        """非法边与过期修订都拒绝，状态文件逐字节不变。"""
        run, _ = self.start_admission()
        before = (run / "state.json").read_bytes()

        stderr = self.failed(
            "advance",
            "prompt-admission",
            "run",
            "--expect",
            0,
            "--event",
            "accepted",
            "--evidence",
            "合成：非法事件",
        )
        self.assertIn("is not available at screen", stderr)

        stderr = self.failed(
            "advance",
            "prompt-admission",
            "run",
            "--expect",
            1,
            "--event",
            "prepared",
            "--evidence",
            "合成：过期修订",
        )
        self.assertIn("revision mismatch: expected 1, found 0", stderr)

        self.assertEqual((run / "state.json").read_bytes(), before)
        status = self.ok_json("status", "prompt-admission", "run", "--history")
        self.assertEqual(status["current"]["id"], "screen")
        self.assertEqual(status["revision"], 0)
        self.assertEqual(status["history"], [])

    def test_concurrent_submissions_of_one_revision_accept_exactly_one(self):
        """同一修订号的并发提交只有一个成功，历史只记一条。"""
        run, _ = self.start_admission()
        attempts = 8
        processes = [
            subprocess.Popen(
                [
                    PYTHON,
                    "-B",
                    str(self.control),
                    "advance",
                    "prompt-admission",
                    "run",
                    "--expect",
                    "0",
                    "--event",
                    "prepared",
                    "--evidence",
                    f"合成：并发提交 {index}",
                ],
                cwd=str(self.root),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for index in range(attempts)
        ]
        outputs = [process.communicate() for process in processes]
        codes = [process.returncode for process in processes]

        self.assertEqual(codes.count(0), 1, codes)
        for (stdout, stderr), code in zip(outputs, codes):
            if code == 0:
                self.assertEqual(json.loads(stdout)["revision"], 1)
            else:
                self.assertEqual(code, 1, stderr)
                self.assertIn("revision mismatch", stderr)
                self.assertEqual(stdout, "")

        winner = codes.index(0)
        status = self.ok_json("status", "prompt-admission", "run", "--history")
        self.assertEqual(status["revision"], 1)
        self.assertEqual(len(status["history"]), 1)
        self.assertEqual(status["history"][0]["event"], "prepared")
        self.assertEqual(status["history"][0]["evidence"], f"合成：并发提交 {winner}")
        self.assertEqual(
            len(json.loads((run / "state.json").read_text("utf-8"))["history"]), 1
        )

    def test_run_keeps_started_definition_snapshot(self):
        """启动后改 YAML 文件，已有运行仍读冻结快照。"""
        run, started = self.start_admission(run_id="frozen-run")
        definition = self.pub / "prompt-admission" / "pipeline.yaml"
        replacement = self.write_definition("prompt-admission", REPLACEMENT_YAML)
        self.assertEqual(definition, replacement)
        validated = self.ok_json("validate", replacement)
        self.assertEqual(validated["pipeline"], "replacement")
        self.assertNotEqual(validated["definition_sha256"], started["definition_sha256"])

        status = self.ok_json(
            "status", "prompt-admission", "frozen-run", cwd=self.toolkit
        )
        self.assertEqual(status["run_dir"], str(run))
        self.assertEqual(status["pipeline"], "prompt-admission")
        self.assertEqual(status["definition_sha256"], started["definition_sha256"])
        self.assertEqual(status["current"]["id"], "screen")

        result = self.ok_json(
            "advance",
            "prompt-admission",
            "frozen-run",
            "--expect",
            0,
            "--event",
            "prepared",
            "--evidence",
            "合成：按冻结定义推进",
        )
        self.assertEqual(result["current"]["id"], "review")
        self.assertEqual(result["revision"], 1)

    def test_rejects_yaml_without_exit_or_with_unknown_target(self):
        """无终点路径与未知目标都被 validate 拒绝；非法 start 不建运行目录。"""
        no_exit = self.write_definition("no-exit", NO_EXIT_YAML)
        stderr = self.failed("validate", no_exit)
        self.assertIn("no path to a final from: a, b", stderr)

        unknown = self.write_definition("unknown-target", UNKNOWN_TARGET_YAML)
        stderr = self.failed("validate", unknown)
        self.assertIn("unknown target missing", stderr)

        run = self.run_dir("unknown-target", "invalid-run")
        stderr = self.failed("start", "unknown-target", "invalid-run")
        self.assertIn("unknown target missing", stderr)
        self.assertFalse(run.exists())

    def test_duplicate_event_key_and_unsupported_yaml_forms_create_no_run(self):
        """重复事件键、锚点和显式标签都被真实 CLI 拒绝，且不建运行目录。"""
        cases = [
            ("duplicate-event", DUPLICATE_EVENT_YAML, "duplicate YAML key"),
            ("anchor", ANCHOR_YAML, "YAML anchors, aliases and explicit tags are not supported"),
            ("tag", TAG_YAML, "YAML anchors, aliases and explicit tags are not supported"),
        ]
        for name, body, message in cases:
            with self.subTest(definition=name):
                self.write_definition(name, body)
                run = self.run_dir(name, f"{name}-run")
                stderr = self.failed("start", name, f"{name}-run")
                self.assertIn(message, stderr)
                self.assertFalse(run.exists())

    def test_private_definition_runs_from_any_cwd_without_pub_output(self):
        """只有 pri 定义也可启动；不同 CWD 返回正确 run_dir，pub 无产出。"""
        self.write_definition("prompt-admission", ADMISSION_YAML, scope="pri")
        self.assertFalse((self.pub / "prompt-admission").exists())
        run = self.run_dir("prompt-admission", "private-run")

        started = self.ok_json("start", "prompt-admission", "private-run", cwd=self.root)
        self.assertEqual(started["run_dir"], str(run))
        self.assertEqual(
            (started["pipeline"], started["current"]["id"]), ("prompt-admission", "screen")
        )

        status = self.ok_json(
            "status", "prompt-admission", "private-run", cwd=self.toolkit
        )
        self.assertEqual((status["status"], status["run_dir"]), ("running", str(run)))

        advanced = self.ok_json(
            "advance",
            "prompt-admission",
            "private-run",
            "--expect",
            0,
            "--event",
            "prepared",
            "--evidence",
            "合成：私有定义推进",
            cwd=self.pri,
        )
        self.assertEqual(
            (advanced["current"]["id"], advanced["revision"], advanced["run_dir"]),
            ("review", 1, str(run)),
        )
        self.assertEqual(self.pub_entries(), [])
        self.assertEqual(
            sorted(path.relative_to(run).as_posix() for path in run.iterdir()),
            ["state.json"],
        )

    def test_status_graph_exports_read_only_replay_input(self):
        """status --graph 补齐查看器所需图结构，且不改变运行状态。"""
        run, _ = self.start_admission(run_id="viewer-run")
        before = (run / "state.json").read_bytes()

        result = self.ok_json(
            "status",
            "prompt-admission",
            "viewer-run",
            "--history",
            "--graph",
        )

        self.assertEqual(result["initial"], "screen")
        self.assertEqual(
            [node["id"] for node in result["nodes"]],
            ["screen", "review", "monitor", "approve", "admitted"],
        )
        self.assertEqual(result["history"], [])
        self.assertEqual((run / "state.json").read_bytes(), before)

    def test_ambiguous_and_misnamed_definitions_are_rejected(self):
        """pub/pri 双定义与目录名、id 不符都在建运行目录前拒绝。"""
        dual_pub = self.write_definition("ambiguous", single_step("ambiguous"))
        dual_pri = self.write_definition(
            "ambiguous", single_step("ambiguous"), scope="pri"
        )
        dual_run = self.run_dir("ambiguous", "dual-run")
        stderr = self.failed("start", "ambiguous", "dual-run")
        self.assertIn("has definitions in both pub and pri", stderr)
        self.assertFalse(dual_run.exists())
        self.assertFalse((self.pri / "ambiguous" / "runs").exists())
        self.assertEqual(dual_pub.read_text(encoding="utf-8"), single_step("ambiguous"))
        self.assertEqual(dual_pri.read_text(encoding="utf-8"), single_step("ambiguous"))

        misnamed = self.write_definition("misnamed", single_step("other-name"))
        run = self.run_dir("misnamed", "misnamed-run")
        stderr = self.failed("start", "misnamed", "misnamed-run")
        self.assertIn(
            "definition id 'other-name' does not match pipeline 'misnamed'", stderr
        )
        self.assertFalse(run.exists())
        self.assertFalse((self.pri / "misnamed").exists())
        self.assertEqual(misnamed.read_text(encoding="utf-8"), single_step("other-name"))

    def test_identifier_and_symlink_boundaries_do_not_write_outside_layout(self):
        """非法名称在打开路径前被拒；定义与运行路径的符号链接都不被跟随。"""
        self.write_definition("loop-budget", LOOP_YAML)
        stderr = self.failed("start", "Bad_Name", "run-1")
        self.assertIn("invalid pipeline name", stderr)
        stderr = self.failed("start", "loop-budget", "../escape")
        self.assertIn("invalid run id", stderr)
        self.assertEqual(list(self.pri.rglob("*")), [])

        outside = self.root / "outside"
        outside.mkdir()
        linked_definition = outside / "pipeline.yaml"
        linked_definition.write_text(
            LOOP_YAML.replace("id: loop-budget", "id: symlinked"), encoding="utf-8"
        )
        definition_link = self.pub / "symlinked" / "pipeline.yaml"
        definition_link.parent.mkdir()
        definition_link.symlink_to(linked_definition)
        stderr = self.failed("start", "symlinked", "linked-run")
        self.assertIn(
            "pipeline layout does not accept symlinks: pub/symlinked/pipeline.yaml",
            stderr,
        )
        self.assertEqual(
            sorted(path.name for path in outside.iterdir()), ["pipeline.yaml"]
        )

        run_target = outside / "run-target"
        run_target.mkdir()
        (self.pri / "loop-budget").symlink_to(run_target)
        stderr = self.failed("start", "loop-budget", "linked-run")
        self.assertIn(
            "pipeline layout does not accept symlinks: pri/loop-budget", stderr
        )
        self.assertEqual(list(run_target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
