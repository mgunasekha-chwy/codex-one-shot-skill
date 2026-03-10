#!/usr/bin/env bash
set -euo pipefail

JIRA_KEY="${1:?usage: spawn_tmux_worktrees.sh JIRA-123 <plan.json> <packets_dir>}"
PLAN_JSON="${2:?usage: spawn_tmux_worktrees.sh JIRA-123 <plan.json> <packets_dir>}"
PACKETS_DIR="${3:?usage: spawn_tmux_worktrees.sh JIRA-123 <plan.json> <packets_dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRADLE_WRAPPER_SOURCE="${SCRIPT_DIR}/codex-gradle-test.sh"

WORKSPACE_ROOT="${WORKSPACE_ROOT:-$(pwd)}"
BASE_BRANCH="${BASE_BRANCH:-main}"

require() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 2; }; }
require git
require tmux
require python3
require codex

if [[ ! -f "${GRADLE_WRAPPER_SOURCE}" ]]; then
  echo "Missing helper script: ${GRADLE_WRAPPER_SOURCE}" >&2
  exit 2
fi

# Read repos from plan.json (expects repos[].name and optional repos[].local_path and repos[].branch)
REPOS_JSON="$(python3 - "$PLAN_JSON" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
print(json.dumps(p["repos"]))
PY
)"

SESSION="codex-${JIRA_KEY}"
tmux has-session -t "$SESSION" 2>/dev/null && { echo "tmux session $SESSION already exists" >&2; exit 2; }

repo_count="$(python3 - "$REPOS_JSON" <<'PY'
import json,sys
a=json.loads(sys.argv[1])
print(len(a))
PY
)"

if [[ "$repo_count" -lt 1 ]]; then
  echo "No repos in plan" >&2
  exit 2
fi

pane_cmd_for_index() {
  local idx="$1"
  python3 - <<'PY' "$REPOS_JSON" "$idx" "$WORKSPACE_ROOT" "$BASE_BRANCH" "$PACKETS_DIR" "$JIRA_KEY" "$GRADLE_WRAPPER_SOURCE"
import json,sys,os
repos=json.loads(sys.argv[1]); i=int(sys.argv[2])
workspace=sys.argv[3]; base=sys.argv[4]; packets=sys.argv[5]; jira=sys.argv[6]; gradle_wrapper=sys.argv[7]
r=repos[i]
name=r["name"]
local_path=r.get("local_path") or os.path.join(workspace, name.split("/")[-1])
branch=r.get("branch") or f"{jira}-{name}".replace("/","-")
packet=os.path.join(packets, f"{name.replace('/','-')}.md")

# Worktree location: sibling folder to repo clone
wt=os.path.join(os.path.dirname(local_path), f"{os.path.basename(local_path)}-{jira}")

print(f"""bash -lc '
set -e
cd "{local_path}"
git fetch origin
git worktree add -B "{branch}" "{wt}" "origin/{base}" || (echo "worktree add failed"; exit 2)
cd "{wt}"
if [[ -f ./gradlew ]]; then
  cp "{gradle_wrapper}" ./.codex-gradle-test.sh
  chmod +x ./.codex-gradle-test.sh
fi
codex "$(cat "{packet}")"
'""")
PY
}

first_cmd="$(pane_cmd_for_index 0)"
tmux new-session -d -s "$SESSION" "$first_cmd"

for ((i=1; i<repo_count; i++)); do
  cmd="$(pane_cmd_for_index "$i")"
  tmux split-window -h -t "$SESSION" "$cmd"
  tmux select-layout -t "$SESSION" tiled >/dev/null
done

echo "Workers spawned. Attach with: tmux attach -t $SESSION"
