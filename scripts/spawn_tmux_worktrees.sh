#!/usr/bin/env bash
set -euo pipefail

WORKFLOW_DIR="${1:?usage: spawn_tmux_worktrees.sh <workflow_dir> <iteration_dir>}"
ITERATION_DIR="${2:?usage: spawn_tmux_worktrees.sh <workflow_dir> <iteration_dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRADLE_WRAPPER_SOURCE="${SCRIPT_DIR}/codex-gradle-test.sh"
PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONPATH

WORKER_SHELL="${SHELL:-/bin/bash}"

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
require tmux
require python3
require codex

if [[ ! -x "${WORKER_SHELL}" ]]; then
  WORKER_SHELL="/bin/bash"
fi

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

SESSION="$(python3 - "$WORKFLOW_DIR" "$ITERATION_DIR" <<'PY'
import sys
from paper_trail import load_iteration, load_workflow
workflow_path, workflow = load_workflow(sys.argv[1])
iteration_path, iteration = load_iteration(sys.argv[2])
short = workflow["workflow_id"].split("-", 1)[0]
print(f"codex-{workflow['jira_key']}-{short}-i{iteration['iteration']:03d}")
PY
)"

tmux has-session -t "$SESSION" 2>/dev/null && {
  echo "tmux session already exists: $SESSION" >&2
  exit 2
}

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
DEFAULT_GRADLE_PROPERTIES_SOURCE="${HOME}/.gradle/gradle.properties"
mkdir -p "${SHARED_GRADLE_USER_HOME}"

if [[ -f "${DEFAULT_GRADLE_PROPERTIES_SOURCE}" && ! -f "${SHARED_GRADLE_USER_HOME}/gradle.properties" ]]; then
  cp "${DEFAULT_GRADLE_PROPERTIES_SOURCE}" "${SHARED_GRADLE_USER_HOME}/gradle.properties"
fi

pane_cmd_for_index() {
  local idx="$1"
  python3 - "$WORKFLOW_DIR" "$idx" "$GRADLE_WRAPPER_SOURCE" "$WORKER_SHELL" "$SHARED_GRADLE_USER_HOME" <<'PY'
import shlex
import sys
from paper_trail import load_workflow

_, workflow = load_workflow(sys.argv[1])
repo = workflow["repos"][int(sys.argv[2])]
gradle_wrapper = sys.argv[3]
worker_shell = sys.argv[4]
shared_gradle_user_home = sys.argv[5]
base = workflow.get("base_branch", "main")

local_path = repo["local_path"]
worktree_path = repo["worktree_path"]
branch = repo["branch"]

script = f"""
set -e
cd {shlex.quote(local_path)}
git fetch origin
if [[ -e {shlex.quote(worktree_path)} ]]; then
  if ! git -C {shlex.quote(worktree_path)} rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Existing path is not a git worktree: {worktree_path}" >&2
    exit 2
  fi
  actual_branch="$(git -C {shlex.quote(worktree_path)} branch --show-current)"
  if [[ "$actual_branch" != {shlex.quote(branch)} ]]; then
    echo "Existing worktree {worktree_path} is on branch $actual_branch, expected {branch}" >&2
    exit 2
  fi
else
  git worktree add --no-track -B {shlex.quote(branch)} {shlex.quote(worktree_path)} origin/{shlex.quote(base)} || (
    echo "Failed to create worktree {worktree_path}" >&2
    exit 2
  )
fi
cd {shlex.quote(worktree_path)}
if [[ -f ./gradlew ]]; then
  cp {shlex.quote(gradle_wrapper)} ./.codex-gradle-test.sh
  chmod +x ./.codex-gradle-test.sh
  export CODEX_SHARED_GRADLE_USER_HOME={shlex.quote(shared_gradle_user_home)}
  ./.codex-gradle-test.sh --version
fi
exec codex
"""
print(f"{shlex.quote(worker_shell)} -lc {shlex.quote(script)}")
PY
}

declare -a PANE_IDS=()

first_cmd="$(pane_cmd_for_index 0)"
first_pane_id="$(tmux new-session -d -P -F '#{pane_id}' -s "$SESSION" "$first_cmd")"
PANE_IDS+=("$first_pane_id")

for ((i=1; i<repo_count; i++)); do
  cmd="$(pane_cmd_for_index "$i")"
  pane_id="$(tmux split-window -h -P -F '#{pane_id}' -t "$SESSION" "$cmd")"
  PANE_IDS+=("$pane_id")
  tmux select-layout -t "$SESSION" tiled >/dev/null
done

sleep 2

for ((i=0; i<repo_count; i++)); do
  packet_path="$(python3 - "$WORKFLOW_DIR" "$i" <<'PY'
import sys
from paper_trail import load_workflow
_, workflow = load_workflow(sys.argv[1])
print(workflow["repos"][int(sys.argv[2])]["implementation_packet"])
PY
)"
  if [[ ! -f "$packet_path" ]]; then
    echo "Implementation packet not found: $packet_path" >&2
    exit 2
  fi
  buffer_name="packet-${SESSION}-${i}"
  tmux load-buffer -b "$buffer_name" "$packet_path"
  tmux paste-buffer -b "$buffer_name" -t "${PANE_IDS[$i]}"
  tmux send-keys -t "${PANE_IDS[$i]}" Enter
  tmux delete-buffer -b "$buffer_name"
done

python3 - "$WORKFLOW_DIR" "$ITERATION_DIR" "$SESSION" "${PANE_IDS[@]}" <<'PY'
import sys
from paper_trail import load_iteration, load_workflow, save_iteration, save_workflow, utc_now

workflow_path, workflow = load_workflow(sys.argv[1])
iteration_path, iteration = load_iteration(sys.argv[2])
session = {
    "mode": "implement",
    "session": sys.argv[3],
    "iteration": iteration["iteration"],
    "pane_ids": sys.argv[4:],
    "created_at": utc_now(),
}
workflow.setdefault("sessions", []).append(session)
workflow["updated_at"] = utc_now()
iteration["implement_session"] = session
iteration["updated_at"] = utc_now()
save_workflow(workflow_path, workflow)
save_iteration(iteration_path, iteration)
PY

echo "Workers spawned. Attach with: tmux attach -t $SESSION"
