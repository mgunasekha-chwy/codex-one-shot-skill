#!/usr/bin/env bash
set -euo pipefail

# Historical name kept for skill compatibility. This launcher must not create
# interactive tmux/Codex sessions; workers run to completion through codex exec.
WORKFLOW_DIR="${1:?usage: spawn_tmux_worktrees.sh <workflow_dir> <iteration_dir>}"
ITERATION_DIR="${2:?usage: spawn_tmux_worktrees.sh <workflow_dir> <iteration_dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRADLE_WRAPPER_SOURCE="${SCRIPT_DIR}/codex-gradle-test.sh"
PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONPATH

abs_path() {
  local path="$1"
  if [[ -d "$path" ]]; then
    (cd "$path" && pwd)
  else
    (cd "$(dirname "$path")" && printf "%s/%s\n" "$(pwd)" "$(basename "$path")")
  fi
}

WORKFLOW_DIR="$(abs_path "$WORKFLOW_DIR")"
ITERATION_DIR="$(abs_path "$ITERATION_DIR")"

require() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 2; }; }
require git
require python3
require codex

if [[ ! -f "${GRADLE_WRAPPER_SOURCE}" ]]; then
  echo "Missing helper script: ${GRADLE_WRAPPER_SOURCE}" >&2
  exit 2
fi

if [[ ! -f "${WORKFLOW_DIR}/workflow_manifest.json" ]]; then
  echo "Workflow manifest not found: ${WORKFLOW_DIR}/workflow_manifest.json" >&2
  exit 2
fi

if [[ ! -f "${ITERATION_DIR}/iteration_manifest.json" ]]; then
  echo "Iteration manifest not found: ${ITERATION_DIR}/iteration_manifest.json" >&2
  exit 2
fi

repo_count="$(python3 - "$WORKFLOW_DIR" <<'PY'
import sys
from paper_trail import load_workflow
_, workflow = load_workflow(sys.argv[1])
print(len(workflow.get("repos", [])))
PY
)"

if [[ "$repo_count" -lt 1 ]]; then
  echo "Workflow manifest has no repos; run write_work_packets.py first" >&2
  exit 2
fi

SHARED_GRADLE_USER_HOME="$(python3 - "$WORKFLOW_DIR" <<'PY'
import sys
from pathlib import Path
from paper_trail import load_workflow
_, workflow = load_workflow(sys.argv[1])
workspace = workflow.get("workspace_root") or workflow.get("invocation_cwd")
print(Path(workspace) / ".gradle-user-home")
PY
)"
BASE_BRANCH="$(python3 - "$WORKFLOW_DIR" <<'PY'
import sys
from paper_trail import load_workflow
_, workflow = load_workflow(sys.argv[1])
print(workflow.get("base_branch", "main"))
PY
)"
DEFAULT_GRADLE_PROPERTIES_SOURCE="${HOME}/.gradle/gradle.properties"
mkdir -p "${SHARED_GRADLE_USER_HOME}"

if [[ -f "${DEFAULT_GRADLE_PROPERTIES_SOURCE}" && ! -f "${SHARED_GRADLE_USER_HOME}/gradle.properties" ]]; then
  cp "${DEFAULT_GRADLE_PROPERTIES_SOURCE}" "${SHARED_GRADLE_USER_HOME}/gradle.properties"
fi

REPO_ROWS="$(
python3 - "$WORKFLOW_DIR" "$ITERATION_DIR" <<'PY'
import sys
from paper_trail import implementation_log_path, implementation_output_path, load_iteration, load_workflow

_, workflow = load_workflow(sys.argv[1])
iteration_path, _ = load_iteration(sys.argv[2])
for repo in workflow.get("repos", []):
    fields = [
        repo["name"],
        repo["local_path"],
        repo["worktree_path"],
        repo["branch"],
        repo["implementation_packet"],
        str(implementation_output_path(iteration_path, repo["name"])),
        str(implementation_log_path(iteration_path, repo["name"])),
    ]
    print("\t".join(fields))
PY
)"

declare -a PIDS=()
declare -a REPO_NAMES=()
declare -a OUTPUT_PATHS=()
declare -a LOG_PATHS=()
declare -a EXIT_CODES=()

while IFS= read -r row; do
  [[ -n "$row" ]] || continue
  IFS=$'\t' read -r repo_name local_path worktree_path branch packet_path output_path log_path <<<"$row"

  if [[ ! -f "$packet_path" ]]; then
    echo "Implementation packet not found: $packet_path" >&2
    exit 2
  fi

  mkdir -p "$(dirname "$output_path")" "$(dirname "$log_path")"

  cd "$local_path"
  git fetch origin
  if [[ -e "$worktree_path" ]]; then
    if ! git -C "$worktree_path" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      echo "Existing path is not a git worktree: $worktree_path" >&2
      exit 2
    fi
    actual_branch="$(git -C "$worktree_path" branch --show-current)"
    if [[ "$actual_branch" != "$branch" ]]; then
      echo "Existing worktree $worktree_path is on branch $actual_branch, expected $branch" >&2
      exit 2
    fi
  else
    git worktree add --no-track -B "$branch" "$worktree_path" "origin/$BASE_BRANCH" || (
      echo "Failed to create worktree $worktree_path" >&2
      exit 2
    )
  fi

  cd "$worktree_path"
  if [[ -f ./gradlew ]]; then
    cp "$GRADLE_WRAPPER_SOURCE" ./.codex-gradle-test.sh
    chmod +x ./.codex-gradle-test.sh
    export CODEX_SHARED_GRADLE_USER_HOME="$SHARED_GRADLE_USER_HOME"
    ./.codex-gradle-test.sh --version >/dev/null
  fi

  codex exec --ephemeral --color never --skip-git-repo-check -C "$worktree_path" -o "$output_path" - < "$packet_path" > "$log_path" 2>&1 &
  PIDS+=("$!")
  REPO_NAMES+=("$repo_name")
  OUTPUT_PATHS+=("$output_path")
  LOG_PATHS+=("$log_path")
done <<< "$REPO_ROWS"

overall_status=0
for idx in "${!PIDS[@]}"; do
  if wait "${PIDS[$idx]}"; then
    EXIT_CODES+=(0)
  else
    code=$?
    EXIT_CODES+=("$code")
    overall_status=1
  fi
done

python3 - "$WORKFLOW_DIR" "$ITERATION_DIR" "$overall_status" "${REPO_NAMES[@]}" -- "${OUTPUT_PATHS[@]}" -- "${LOG_PATHS[@]}" -- "${EXIT_CODES[@]}" <<'PY'
import sys
from pathlib import Path

from paper_trail import load_iteration, load_workflow, save_iteration, save_workflow, utc_now

workflow_path, workflow = load_workflow(sys.argv[1])
iteration_path, iteration = load_iteration(sys.argv[2])
overall_status = int(sys.argv[3])

args = sys.argv[4:]
groups = []
current = []
for item in args:
    if item == "--":
        groups.append(current)
        current = []
    else:
        current.append(item)
groups.append(current)
repo_names, output_paths, log_paths, exit_codes = groups

summary_path = Path(iteration["implementation_summary"])
summary_path.parent.mkdir(parents=True, exist_ok=True)
lines = ["# Implementation Summary", ""]
for repo_name, output_path, log_path, exit_code in zip(repo_names, output_paths, log_paths, exit_codes):
    lines.append(f"## {repo_name}")
    lines.append(f"- Output: {output_path}")
    lines.append(f"- Log: {log_path}")
    lines.append(f"- Exit code: {exit_code}")
    lines.append("")
    output_file = Path(output_path)
    if output_file.is_file():
        text = output_file.read_text().strip()
        lines.append(text or "(empty output)")
    else:
        lines.append("(missing output file)")
    lines.append("")
summary_path.write_text("\n".join(lines).rstrip() + "\n")

session = {
    "mode": "implement",
    "runner": "codex-exec",
    "iteration": iteration["iteration"],
    "created_at": utc_now(),
    "completed_at": utc_now(),
    "outputs": output_paths,
    "logs": log_paths,
    "exit_codes": {repo: int(code) for repo, code in zip(repo_names, exit_codes)},
    "status": "success" if overall_status == 0 else "failed",
}
workflow.setdefault("sessions", []).append(session)
workflow["updated_at"] = utc_now()
iteration["implement_session"] = session
iteration["implementation_outputs"] = output_paths
iteration["implementation_logs"] = log_paths
iteration["updated_at"] = utc_now()
save_workflow(workflow_path, workflow)
save_iteration(iteration_path, iteration)
PY

echo "Implementation complete: ${ITERATION_DIR}/summaries/implementation.md"
exit "$overall_status"
