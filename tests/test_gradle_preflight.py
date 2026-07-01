#!/usr/bin/env python3
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_executable(path, content):
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class GradlePreflightTests(unittest.TestCase):
    def make_git_repo(self, root):
        subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def make_plan_and_packet(self, workspace, repo_path):
        plan = {
            "jira_key": "AGC-187",
            "repos": [
                {
                    "name": "example-repo",
                    "local_path": str(repo_path),
                    "build_tool": "gradle",
                }
            ],
        }
        plan_path = workspace / "plan.json"
        packets_dir = workspace / "packets"
        packets_dir.mkdir()
        plan_path.write_text(json.dumps(plan))
        (packets_dir / "example-repo.md").write_text("# packet\n")
        return plan_path, packets_dir

    def make_fake_tools(self, workspace, tmux_log=None):
        bin_dir = workspace / "bin"
        bin_dir.mkdir()
        write_executable(bin_dir / "codex", "#!/usr/bin/env bash\nexit 0\n")
        if tmux_log:
            write_executable(
                bin_dir / "tmux",
                f"#!/usr/bin/env bash\necho \"$@\" >> {tmux_log}\nexit 0\n",
            )
        return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

    def test_gradle_wrapper_uses_explicit_java_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repo = workspace / "repo"
            repo.mkdir()
            self.make_git_repo(repo)
            shutil.copy(REPO_ROOT / "scripts" / "codex-gradle-test.sh", repo / ".codex-gradle-test.sh")
            (repo / ".codex-gradle-test.sh").chmod(0o755)

            java_home = workspace / "jdk17"
            (java_home / "bin").mkdir(parents=True)
            write_executable(java_home / "bin" / "java", "#!/usr/bin/env bash\nexit 0\n")
            write_executable(
                repo / "gradlew",
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$JAVA_HOME\" > observed-java-home.txt\n"
                "printf '%s\\n' \"$1\" \"$2\" > observed-args.txt\n",
            )

            env = os.environ.copy()
            env["CODEX_GRADLE_JAVA_HOME"] = str(java_home)
            result = subprocess.run(
                ["./.codex-gradle-test.sh", "help"],
                cwd=repo,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((repo / "observed-java-home.txt").read_text().strip(), str(java_home))
            self.assertIn("-Pgit.root=", (repo / "observed-args.txt").read_text())

    def test_preflight_reports_java_mismatch_retry_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repo = workspace / "repo"
            repo.mkdir()
            self.make_git_repo(repo)
            write_executable(
                repo / "gradlew",
                "#!/usr/bin/env bash\n"
                "echo 'Unsupported class file major version 65' >&2\n"
                "exit 1\n",
            )
            plan_path, packets_dir = self.make_plan_and_packet(workspace, repo)
            env = os.environ.copy()
            env["PATH"] = self.make_fake_tools(workspace)
            env["WORKSPACE_ROOT"] = str(workspace)

            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "scripts" / "preflight_repo_change.sh"),
                    "AGC-187",
                    str(plan_path),
                    str(packets_dir),
                    "single",
                ],
                cwd=workspace,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("Unsupported class file major version 65", result.stderr)
            self.assertIn("CODEX_GRADLE_JAVA_HOME=/path/to/jdk", result.stderr)
            self.assertIn("before starting Codex workers", result.stderr)

    def test_spawn_does_not_call_tmux_when_preflight_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repo = workspace / "repo"
            repo.mkdir()
            self.make_git_repo(repo)
            write_executable(
                repo / "gradlew",
                "#!/usr/bin/env bash\n"
                "echo 'Unsupported class file major version 65' >&2\n"
                "exit 1\n",
            )
            plan_path, packets_dir = self.make_plan_and_packet(workspace, repo)
            tmux_log = workspace / "tmux.log"
            env = os.environ.copy()
            env["PATH"] = self.make_fake_tools(workspace, tmux_log=tmux_log)
            env["WORKSPACE_ROOT"] = str(workspace)

            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "scripts" / "spawn_tmux_worktrees.sh"),
                    "AGC-187",
                    str(plan_path),
                    str(packets_dir),
                ],
                cwd=workspace,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 2)
            self.assertFalse(tmux_log.exists(), result.stderr)


if __name__ == "__main__":
    unittest.main()
