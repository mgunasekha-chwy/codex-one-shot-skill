import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from paper_trail import create_workflow, read_json


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tmp_path = Path(self.temp_dir.name)
        self.stub_bin = self.tmp_path / "bin"
        self.stub_bin.mkdir()
        self.records_dir = self.tmp_path / "records"
        self.records_dir.mkdir()
        self._write_git_stub()
        self._write_codex_stub()
        self._write_tmux_stub()
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(SCRIPTS_DIR)
        self.env["PATH"] = f"{self.stub_bin}:{self.env['PATH']}"
        self.env["CODEX_STUB_RECORD_DIR"] = str(self.records_dir)

    def _write_git_stub(self):
        git_stub = self.stub_bin / "git"
        git_stub.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import sys
                from pathlib import Path

                args = sys.argv[1:]
                if not args:
                    raise SystemExit(2)

                if args[0] == "fetch":
                    raise SystemExit(0)

                if args[0] == "worktree":
                    if len(args) < 7 or args[1] != "add":
                        raise SystemExit(2)
                    branch_idx = args.index("-B")
                    branch = args[branch_idx + 1]
                    path = Path(args[branch_idx + 2])
                    path.mkdir(parents=True, exist_ok=True)
                    (path / ".branch").write_text(branch)
                    raise SystemExit(0)

                if args[0] == "-C":
                    repo_path = Path(args[1])
                    command = args[2:]
                    if command[:2] == ["rev-parse", "--is-inside-work-tree"]:
                        raise SystemExit(0 if repo_path.exists() else 1)
                    if command[:2] == ["branch", "--show-current"]:
                        branch_file = repo_path / ".branch"
                        if branch_file.is_file():
                            sys.stdout.write(branch_file.read_text())
                        raise SystemExit(0)

                raise SystemExit(0)
                """
            )
        )
        git_stub.chmod(0o755)

    def _write_codex_stub(self):
        codex_stub = self.stub_bin / "codex"
        codex_stub.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                import time
                from pathlib import Path

                args = sys.argv[1:]
                stdin_text = sys.stdin.read()
                output_path = None
                workdir = None
                for idx, arg in enumerate(args):
                    if arg in {"-o", "--output-last-message"}:
                        output_path = args[idx + 1]
                    if arg == "-C":
                        workdir = args[idx + 1]

                if workdir is None:
                    workdir = os.getcwd()

                record_dir = Path(os.environ["CODEX_STUB_RECORD_DIR"])
                record = {
                    "args": args,
                    "stdin": stdin_text,
                    "workdir": workdir,
                }
                record_path = record_dir / f"{time.time_ns()}-{os.getpid()}.json"
                record_path.write_text(json.dumps(record))

                mode = "review" if "review" in args else "exec"
                if output_path:
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_text(
                        f"{mode} output for {Path(workdir).name}\\nfirst line: "
                        f"{stdin_text.splitlines()[0] if stdin_text.splitlines() else '(empty)'}\\n"
                    )

                fail_match = os.environ.get("CODEX_STUB_FAIL_MATCH")
                if fail_match and fail_match in workdir:
                    print(f"forced failure for {workdir}", file=sys.stderr)
                    raise SystemExit(7)

                print(f"codex stub ran in {workdir}")
                raise SystemExit(0)
                """
            )
        )
        codex_stub.chmod(0o755)

    def _write_tmux_stub(self):
        tmux_stub = self.stub_bin / "tmux"
        tmux_stub.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import sys

                print(f"tmux must not be called by non-interactive launchers: {' '.join(sys.argv[1:])}", file=sys.stderr)
                raise SystemExit(99)
                """
            )
        )
        tmux_stub.chmod(0o755)

    def _write_plan(self, workflow, repos):
        iteration = workflow / "iteration-001"
        plan = {
            "jira_key": "AGC-124",
            "title": "Test launchers",
            "repos": repos,
        }
        plan_path = workflow / "plan.json"
        plan_path.write_text(json.dumps(plan))
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "write_work_packets.py"),
                str(plan_path),
                str(workflow),
                str(iteration),
            ],
            check=True,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
        )
        return iteration

    def _read_records(self):
        return [
            json.loads(path.read_text())
            for path in sorted(self.records_dir.glob("*.json"))
        ]

    def test_implementation_launcher_runs_codex_exec_and_writes_summary(self):
        workflow = create_workflow(self.tmp_path, "AGC-124", "main")
        repo_a = self.tmp_path / "service-a"
        repo_b = self.tmp_path / "service-b"
        repo_a.mkdir()
        repo_b.mkdir()
        iteration = self._write_plan(
            workflow,
            [
                {
                    "name": "service-a",
                    "local_path": str(repo_a),
                    "branch_suffix": "AGC-124-service-a",
                    "steps": ["Do A"],
                    "tests": ["test-a"],
                },
                {
                    "name": "service-b",
                    "local_path": str(repo_b),
                    "branch_suffix": "AGC-124-service-b",
                    "steps": ["Do B"],
                    "tests": ["test-b"],
                },
            ],
        )

        result = subprocess.run(
            [
                str(SCRIPTS_DIR / "spawn_tmux_worktrees.sh"),
                str(workflow),
                str(iteration),
            ],
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Implementation complete:", result.stdout)
        summary_path = iteration / "summaries" / "implementation.md"
        self.assertTrue(summary_path.is_file())
        summary_text = summary_path.read_text()
        self.assertIn("## service-a", summary_text)
        self.assertIn("## service-b", summary_text)

        iteration_manifest = read_json(iteration / "iteration_manifest.json")
        self.assertEqual(len(iteration_manifest["implementation_outputs"]), 2)
        self.assertEqual(len(iteration_manifest["implementation_logs"]), 2)
        self.assertEqual(iteration_manifest["implement_session"]["runner"], "codex-exec")
        self.assertEqual(iteration_manifest["implement_session"]["status"], "success")

        records = self._read_records()
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertIn("exec", record["args"])
            self.assertIn("--ephemeral", record["args"])
            self.assertIn("--skip-git-repo-check", record["args"])
            self.assertIn("-C", record["args"])
            self.assertNotIn("review", record["args"])
            self.assertTrue(record["stdin"].startswith("# Implementation Packet: "))

    def test_implementation_launcher_persists_logs_on_failure(self):
        workflow = create_workflow(self.tmp_path, "AGC-124", "main")
        repo_a = self.tmp_path / "service-a"
        repo_b = self.tmp_path / "service-b"
        repo_a.mkdir()
        repo_b.mkdir()
        iteration = self._write_plan(
            workflow,
            [
                {
                    "name": "service-a",
                    "local_path": str(repo_a),
                    "branch_suffix": "AGC-124-service-a",
                    "steps": ["Do A"],
                    "tests": ["test-a"],
                },
                {
                    "name": "service-b",
                    "local_path": str(repo_b),
                    "branch_suffix": "AGC-124-service-b",
                    "steps": ["Do B"],
                    "tests": ["test-b"],
                },
            ],
        )

        env = dict(self.env)
        env["CODEX_STUB_FAIL_MATCH"] = "service-b-AGC-124-"
        result = subprocess.run(
            [
                str(SCRIPTS_DIR / "spawn_tmux_worktrees.sh"),
                str(workflow),
                str(iteration),
            ],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 1, msg=result.stderr)
        summary_path = iteration / "summaries" / "implementation.md"
        self.assertTrue(summary_path.is_file())
        manifest = read_json(iteration / "iteration_manifest.json")
        self.assertEqual(manifest["implement_session"]["status"], "failed")
        self.assertEqual(manifest["implement_session"]["exit_codes"]["service-a"], 0)
        self.assertEqual(manifest["implement_session"]["exit_codes"]["service-b"], 7)
        for log_path in manifest["implementation_logs"]:
            self.assertTrue(Path(log_path).is_file())

    def test_single_repo_review_uses_exec_review(self):
        workflow = create_workflow(self.tmp_path, "AGC-124", "main")
        repo_a = self.tmp_path / "service-a"
        repo_a.mkdir()
        iteration = self._write_plan(
            workflow,
            [
                {
                    "name": "service-a",
                    "local_path": str(repo_a),
                    "branch_suffix": "AGC-124-service-a",
                    "steps": ["Do A"],
                    "tests": ["test-a"],
                }
            ],
        )
        workflow_manifest = read_json(workflow / "workflow_manifest.json")
        Path(workflow_manifest["repos"][0]["worktree_path"]).mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "write_review_packet.py"),
                str(workflow),
                str(iteration),
            ],
            check=True,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
        )

        result = subprocess.run(
            [
                str(SCRIPTS_DIR / "spawn_review_tmux.sh"),
                str(workflow),
                str(iteration),
            ],
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Review complete:", result.stdout)
        manifest = read_json(iteration / "iteration_manifest.json")
        self.assertEqual(manifest["review_session"]["runner"], "codex-exec-review")
        self.assertTrue(Path(manifest["review_output"]).is_file())
        self.assertTrue(Path(manifest["review_log"]).is_file())

        records = self._read_records()
        self.assertEqual(len(records), 1)
        args = records[0]["args"]
        self.assertEqual(args[0], "exec")
        self.assertIn("--skip-git-repo-check", args)
        self.assertIn("review", args)
        self.assertIn("--base", args)
        self.assertIn("main", args)

    def test_multi_repo_review_falls_back_to_plain_exec(self):
        workflow = create_workflow(self.tmp_path, "AGC-124", "main")
        repo_a = self.tmp_path / "service-a"
        repo_b = self.tmp_path / "service-b"
        repo_a.mkdir()
        repo_b.mkdir()
        iteration = self._write_plan(
            workflow,
            [
                {
                    "name": "service-a",
                    "local_path": str(repo_a),
                    "branch_suffix": "AGC-124-service-a",
                    "steps": ["Do A"],
                    "tests": ["test-a"],
                },
                {
                    "name": "service-b",
                    "local_path": str(repo_b),
                    "branch_suffix": "AGC-124-service-b",
                    "steps": ["Do B"],
                    "tests": ["test-b"],
                },
            ],
        )
        workflow_manifest = read_json(workflow / "workflow_manifest.json")
        for repo in workflow_manifest["repos"]:
            Path(repo["worktree_path"]).mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "write_review_packet.py"),
                str(workflow),
                str(iteration),
            ],
            check=True,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
        )

        result = subprocess.run(
            [
                str(SCRIPTS_DIR / "spawn_review_tmux.sh"),
                str(workflow),
                str(iteration),
            ],
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        manifest = read_json(iteration / "iteration_manifest.json")
        self.assertEqual(manifest["review_session"]["runner"], "codex-exec")

        records = self._read_records()
        self.assertEqual(len(records), 1)
        args = records[0]["args"]
        self.assertEqual(args[0], "exec")
        self.assertNotIn("review", args)
        self.assertIn("--skip-git-repo-check", args)


if __name__ == "__main__":
    unittest.main()
