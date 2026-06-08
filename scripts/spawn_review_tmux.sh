#!/usr/bin/env bash
set -euo pipefail

WORKFLOW_DIR="${1:?usage: spawn_review_tmux.sh <workflow_dir> [iteration_dir]}"
ITERATION_DIR="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
if [[ -n "$ITERATION_DIR" ]]; then
  ITERATION_DIR="$(abs_path "$ITERATION_DIR")"
else
  ITERATION_DIR="$(python3 - "$WORKFLOW_DIR" <<'PY'
import sys
from paper_trail import latest_iteration
print(latest_iteration(sys.argv[1]))
PY
)"
fi

require() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 2; }; }
require git
require tmux
require python3
require codex

if [[ ! -x "${WORKER_SHELL}" ]]; then
  WORKER_SHELL="/bin/bash"
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
_, workflow = load_workflow(sys.argv[1])
_, iteration = load_iteration(sys.argv[2])
short = workflow["workflow_id"].split("-", 1)[0]
print(f"codex-review-{workflow['jira_key']}-{short}-i{iteration['iteration']:03d}")
PY
)"

tmux has-session -t "$SESSION" 2>/dev/null && {
  echo "tmux session already exists: $SESSION" >&2
  exit 2
}

REVIEW_PACKET="$(python3 - "$ITERATION_DIR" <<'PY'
import sys
from paper_trail import load_iteration
_, iteration = load_iteration(sys.argv[1])
print(iteration.get("review_packet") or "")
PY
)"

if [[ -z "$REVIEW_PACKET" || ! -f "$REVIEW_PACKET" ]]; then
  echo "Review packet not found. Run write_review_packet.py first." >&2
  exit 2
fi

python3 - "$WORKFLOW_DIR" <<'PY'
import subprocess
import sys
from pathlib import Path
from paper_trail import load_workflow

_, workflow = load_workflow(sys.argv[1])
repos = workflow.get("repos", [])
if not repos:
    raise SystemExit("Workflow manifest has no repos to review")
for repo in repos:
    worktree = repo.get("worktree_path")
    if not worktree or not Path(worktree).exists():
        raise SystemExit(f"Recorded worktree does not exist for {repo.get('name')}: {worktree}")
    result = subprocess.run(
        ["git", "-C", worktree, "rev-parse", "--is-inside-work-tree"],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise SystemExit(f"Recorded worktree is not a git worktree for {repo.get('name')}: {worktree}")
PY

review_cmd="$(python3 - "$WORKFLOW_DIR" "$WORKER_SHELL" <<'PY'
import shlex
import sys
workflow_dir = sys.argv[1]
worker_shell = sys.argv[2]
script = f"""
set -e
cd {shlex.quote(workflow_dir)}
exec codex
"""
print(f"{shlex.quote(worker_shell)} -lc {shlex.quote(script)}")
PY
)"

pane_id="$(tmux new-session -d -P -F '#{pane_id}' -s "$SESSION" "$review_cmd")"
sleep 2
buffer_name="packet-${SESSION}"
tmux load-buffer -b "$buffer_name" "$REVIEW_PACKET"
tmux paste-buffer -b "$buffer_name" -t "$pane_id"
tmux send-keys -t "$pane_id" Enter
tmux delete-buffer -b "$buffer_name"

python3 - "$WORKFLOW_DIR" "$ITERATION_DIR" "$SESSION" "$pane_id" <<'PY'
import sys
from paper_trail import load_iteration, load_workflow, save_iteration, save_workflow, utc_now

workflow_path, workflow = load_workflow(sys.argv[1])
iteration_path, iteration = load_iteration(sys.argv[2])
session = {
    "mode": "review",
    "session": sys.argv[3],
    "iteration": iteration["iteration"],
    "pane_ids": [sys.argv[4]],
    "created_at": utc_now(),
}
workflow.setdefault("sessions", []).append(session)
workflow["updated_at"] = utc_now()
iteration["review_session"] = session
iteration["updated_at"] = utc_now()
save_workflow(workflow_path, workflow)
save_iteration(iteration_path, iteration)
PY

echo "Review worker spawned. Attach with: tmux attach -t $SESSION"
