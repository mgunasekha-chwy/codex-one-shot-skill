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

    def make_plan_and_packet(self, workspace, repo_path, repo_config=None):
        repo_config = repo_config or {}
        plan = {
            "jira_key": "AGC-187",
            "repos": [
                {
                    "name": "example-repo",
                    "local_path": str(repo_path),
                    "build_tool": "gradle",
                    **repo_config,
                }
            ],
        }
        return self.write_plan_and_packets(workspace, plan)

    def make_multi_plan_and_packets(self, workspace, repo_paths):
        plan = {
            "jira_key": "AGC-187",
            "repos": [
                {
                    "name": f"example-repo-{i}",
                    "local_path": str(repo_path),
                    "build_tool": "gradle",
                }
                for i, repo_path in enumerate(repo_paths)
            ],
        }
        return self.write_plan_and_packets(workspace, plan)

    def write_plan_and_packets(self, workspace, plan):
        plan_path = workspace / "plan.json"
        packets_dir = workspace / "packets"
        packets_dir.mkdir()
        plan_path.write_text(json.dumps(plan))
        for repo in plan["repos"]:
            (packets_dir / f"{repo['name'].replace('/','-')}.md").write_text("# packet\n")
        return plan_path, packets_dir

    def make_fake_tools(self, workspace, tmux_log=None):
        bin_dir = workspace / "bin"
        bin_dir.mkdir()
        write_executable(bin_dir / "codex", "#!/usr/bin/env bash\nexit 0\n")
        if tmux_log:
            write_executable(
                bin_dir / "tmux",
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"has-session\" ]]; then exit 1; fi\n"
                f"echo \"$@\" >> {tmux_log}\n"
                "printf '%%1\\n'\n"
                "exit 0\n",
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

    def test_preflight_defaults_to_compile_java(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repo = workspace / "repo"
            repo.mkdir()
            self.make_git_repo(repo)
            write_executable(
                repo / "gradlew",
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$1\" \"$2\" > observed-args.txt\n",
            )
            plan_path, packets_dir = self.make_plan_and_packet(workspace, repo)
            env = os.environ.copy()
            env["PATH"] = self.make_fake_tools(workspace)
            env["WORKSPACE_ROOT"] = str(workspace)
            env.pop("CODEX_GRADLE_PREFLIGHT_ARGS", None)

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

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("compileJava", (repo / "observed-args.txt").read_text())

    def test_preflight_does_not_export_java_override_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repo = workspace / "repo"
            repo.mkdir()
            self.make_git_repo(repo)
            write_executable(
                repo / "gradlew",
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"${CODEX_GRADLE_JAVA_HOME:-}\" > observed-codex-java-home.txt\n",
            )
            plan_path, packets_dir = self.make_plan_and_packet(workspace, repo)
            env = os.environ.copy()
            env["PATH"] = self.make_fake_tools(workspace)
            env["WORKSPACE_ROOT"] = str(workspace)
            env.pop("CODEX_GRADLE_JAVA_HOME", None)

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

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((repo / "observed-codex-java-home.txt").read_text().strip(), "")

    def test_preflight_uses_per_repo_java_home_for_mixed_jdk_repos(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repos = [workspace / "repo17", workspace / "repo21"]
            java_homes = [workspace / "jdk17", workspace / "jdk21"]
            for repo in repos:
                repo.mkdir()
                self.make_git_repo(repo)
                write_executable(
                    repo / "gradlew",
                    "#!/usr/bin/env bash\n"
                    "printf '%s\\n' \"$JAVA_HOME\" > observed-java-home.txt\n",
                )
            for java_home in java_homes:
                (java_home / "bin").mkdir(parents=True)
                write_executable(java_home / "bin" / "java", "#!/usr/bin/env bash\nexit 0\n")
            plan = {
                "jira_key": "AGC-187",
                "repos": [
                    {
                        "name": "example-repo-17",
                        "local_path": str(repos[0]),
                        "build_tool": "gradle",
                        "gradle_java_home": str(java_homes[0]),
                    },
                    {
                        "name": "example-repo-21",
                        "local_path": str(repos[1]),
                        "build_tool": "gradle",
                        "gradle_java_home": str(java_homes[1]),
                    },
                ],
            }
            plan_path, packets_dir = self.write_plan_and_packets(workspace, plan)
            env = os.environ.copy()
            env["PATH"] = self.make_fake_tools(workspace, tmux_log=workspace / "tmux.log")
            env["WORKSPACE_ROOT"] = str(workspace)

            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "scripts" / "preflight_repo_change.sh"),
                    "AGC-187",
                    str(plan_path),
                    str(packets_dir),
                    "multi",
                ],
                cwd=workspace,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((repos[0] / "observed-java-home.txt").read_text().strip(), str(java_homes[0]))
            self.assertEqual((repos[1] / "observed-java-home.txt").read_text().strip(), str(java_homes[1]))

    def test_preflight_uses_global_java_home_when_repo_has_no_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repo = workspace / "repo"
            repo.mkdir()
            self.make_git_repo(repo)
            java_home = workspace / "jdk17"
            (java_home / "bin").mkdir(parents=True)
            write_executable(java_home / "bin" / "java", "#!/usr/bin/env bash\nexit 0\n")
            write_executable(
                repo / "gradlew",
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$JAVA_HOME\" > observed-java-home.txt\n",
            )
            plan_path, packets_dir = self.make_plan_and_packet(workspace, repo)
            env = os.environ.copy()
            env["PATH"] = self.make_fake_tools(workspace)
            env["WORKSPACE_ROOT"] = str(workspace)
            env["CODEX_GRADLE_JAVA_HOME"] = str(java_home)

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

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((repo / "observed-java-home.txt").read_text().strip(), str(java_home))

    def test_spawn_does_not_call_tmux_when_preflight_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repo = workspace / "repo"
            other_repo = workspace / "other-repo"
            repo.mkdir()
            other_repo.mkdir()
            self.make_git_repo(repo)
            self.make_git_repo(other_repo)
            write_executable(
                repo / "gradlew",
                "#!/usr/bin/env bash\n"
                "echo 'Unsupported class file major version 65' >&2\n"
                "exit 1\n",
            )
            write_executable(other_repo / "gradlew", "#!/usr/bin/env bash\nexit 0\n")
            plan_path, packets_dir = self.make_multi_plan_and_packets(workspace, [repo, other_repo])
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

    def test_spawn_exports_per_repo_java_home_to_worker_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            repos = [workspace / "repo17", workspace / "repo21"]
            java_homes = [workspace / "jdk17", workspace / "jdk21"]
            for repo in repos:
                repo.mkdir()
                self.make_git_repo(repo)
                write_executable(repo / "gradlew", "#!/usr/bin/env bash\nexit 0\n")
            for java_home in java_homes:
                (java_home / "bin").mkdir(parents=True)
                write_executable(java_home / "bin" / "java", "#!/usr/bin/env bash\nexit 0\n")
            plan = {
                "jira_key": "AGC-187",
                "repos": [
                    {
                        "name": "example-repo-17",
                        "local_path": str(repos[0]),
                        "build_tool": "gradle",
                        "gradle_java_home": str(java_homes[0]),
                    },
                    {
                        "name": "example-repo-21",
                        "local_path": str(repos[1]),
                        "build_tool": "gradle",
                        "gradle_java_home": str(java_homes[1]),
                    },
                ],
            }
            plan_path, packets_dir = self.write_plan_and_packets(workspace, plan)
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

            self.assertEqual(result.returncode, 0, result.stderr)
            log = tmux_log.read_text()
            self.assertIn(f'export CODEX_GRADLE_JAVA_HOME="{java_homes[0]}"', log)
            self.assertIn(f'export CODEX_GRADLE_JAVA_HOME="{java_homes[1]}"', log)


if __name__ == "__main__":
    unittest.main()
