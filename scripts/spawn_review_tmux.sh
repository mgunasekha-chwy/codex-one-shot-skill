#!/usr/bin/env bash
set -euo pipefail

WORKFLOW_DIR="${1:?usage: spawn_review_tmux.sh <workflow_dir> [iteration_dir]}"
ITERATION_DIR="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
require python3
require codex

if [[ ! -f "${WORKFLOW_DIR}/workflow_manifest.json" ]]; then
  echo "Workflow manifest not found: ${WORKFLOW_DIR}/workflow_manifest.json" >&2
  exit 2
fi

if [[ ! -f "${ITERATION_DIR}/iteration_manifest.json" ]]; then
  echo "Iteration manifest not found: ${ITERATION_DIR}/iteration_manifest.json" >&2
  exit 2
fi

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

REVIEW_INFO="$(
python3 - "$WORKFLOW_DIR" "$ITERATION_DIR" <<'PY'
import subprocess
import sys
from pathlib import Path

from paper_trail import load_iteration, load_workflow

_, workflow = load_workflow(sys.argv[1])
_, iteration = load_iteration(sys.argv[2])
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

print(len(repos))
print(repos[0]["worktree_path"])
print(workflow.get("base_branch", "main"))
print(iteration["review_output"])
print(iteration["review_log"])
PY
)"

review_index=0
while IFS= read -r review_line; do
  case "$review_index" in
    0) repo_count="$review_line" ;;
    1) primary_worktree="$review_line" ;;
    2) base_branch="$review_line" ;;
    3) review_output="$review_line" ;;
    4) review_log="$review_line" ;;
  esac
  review_index=$((review_index + 1))
done <<< "$REVIEW_INFO"

mkdir -p "$(dirname "$review_output")" "$(dirname "$review_log")"

review_status=0
if [[ "$repo_count" == "1" ]]; then
  if codex exec --ephemeral --color never -C "$primary_worktree" -o "$review_output" review --base "$base_branch" - < "$REVIEW_PACKET" > "$review_log" 2>&1; then
    :
  else
    review_status=$?
  fi
else
  if codex exec --ephemeral --color never --skip-git-repo-check -C "$WORKFLOW_DIR" -o "$review_output" - < "$REVIEW_PACKET" > "$review_log" 2>&1; then
    :
  else
    review_status=$?
  fi
fi

python3 - "$WORKFLOW_DIR" "$ITERATION_DIR" "$review_status" <<'PY'
import sys

from paper_trail import load_iteration, load_workflow, save_iteration, save_workflow, utc_now

workflow_path, workflow = load_workflow(sys.argv[1])
iteration_path, iteration = load_iteration(sys.argv[2])
review_status = int(sys.argv[3])
session = {
    "mode": "review",
    "runner": "codex-exec-review" if len(workflow.get("repos", [])) == 1 else "codex-exec",
    "iteration": iteration["iteration"],
    "created_at": utc_now(),
    "completed_at": utc_now(),
    "output": iteration["review_output"],
    "log": iteration["review_log"],
    "status": "success" if review_status == 0 else "failed",
    "exit_code": review_status,
}
workflow.setdefault("sessions", []).append(session)
workflow["updated_at"] = utc_now()
iteration["review_session"] = session
iteration["updated_at"] = utc_now()
save_workflow(workflow_path, workflow)
save_iteration(iteration_path, iteration)
PY

echo "Review complete: ${review_output}"
exit "$review_status"
