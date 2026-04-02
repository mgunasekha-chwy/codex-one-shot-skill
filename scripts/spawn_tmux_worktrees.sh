#!/usr/bin/env bash
set -euo pipefail

JIRA_KEY="${1:?usage: spawn_tmux_worktrees.sh JIRA-123 <plan.json> <packets_dir>}"
PLAN_JSON="${2:?usage: spawn_tmux_worktrees.sh JIRA-123 <plan.json> <packets_dir>}"
PACKETS_DIR="${3:?usage: spawn_tmux_worktrees.sh JIRA-123 <plan.json> <packets_dir>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRADLE_WRAPPER_SOURCE="${SCRIPT_DIR}/codex-gradle-test.sh"

WORKSPACE_ROOT="${WORKSPACE_ROOT:-$(pwd)}"
BASE_BRANCH="${BASE_BRANCH:-main}"

abs_path() {
  local path="$1"
  if [[ -d "$path" ]]; then
    (cd "$path" && pwd)
  else
    (cd "$(dirname "$path")" && printf "%s/%s\n" "$(pwd)" "$(basename "$path")")
  fi
}

PLAN_JSON="$(abs_path "$PLAN_JSON")"
PACKETS_DIR="$(abs_path "$PACKETS_DIR")"

require() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 2; }; }
require git
require tmux
require python3
require codex

if [[ ! -f "${GRADLE_WRAPPER_SOURCE}" ]]; then
  echo "Missing helper script: ${GRADLE_WRAPPER_SOURCE}" >&2
  exit 2
fi

if [[ ! -f "${PLAN_JSON}" ]]; then
  echo "Plan file not found: ${PLAN_JSON}" >&2
  exit 2
fi

if [[ ! -d "${PACKETS_DIR}" ]]; then
  echo "Packets directory not found: ${PACKETS_DIR}" >&2
  exit 2
fi

# Read repos from plan.json (expects repos[].name and optional repos[].local_path and repos[].branch)
PLAN_JSON_CONTENT="$(python3 - "$PLAN_JSON" <<'PY'
import json,sys
print(json.dumps(json.load(open(sys.argv[1]))))
PY
)"

SESSION="codex-${JIRA_KEY}"
tmux has-session -t "$SESSION" 2>/dev/null && { echo "tmux session $SESSION already exists" >&2; exit 2; }

repo_count="$(python3 - "$PLAN_JSON_CONTENT" <<'PY'
import json,sys
plan=json.loads(sys.argv[1])
print(len(plan["repos"]))
PY
)"

if [[ "$repo_count" -lt 1 ]]; then
  echo "No repos in plan" >&2
  exit 2
fi

pane_cmd_for_index() {
  local idx="$1"
  python3 - <<'PY' "$PLAN_JSON_CONTENT" "$idx" "$WORKSPACE_ROOT" "$BASE_BRANCH" "$PACKETS_DIR" "$JIRA_KEY" "$GRADLE_WRAPPER_SOURCE"
import json,sys,os,re

def infer_branch_prefix(plan, repo_config):
    explicit_value = repo_config.get("branch_type") or plan.get("branch_type")
    if explicit_value:
        normalized = str(explicit_value).strip().lower()
        if normalized in {"bugfix", "bug", "fix", "hotfix"}:
            return "bugfix"
        if normalized in {"feature", "feat"}:
            return "feature"

    explicit_text = " ".join(
        str(value)
        for value in (
            repo_config.get("story_type"),
            plan.get("story_type"),
            repo_config.get("issue_type"),
            plan.get("issue_type"),
            plan.get("title"),
            plan.get("summary"),
        )
        if value
    ).lower()
    if re.search(r"\b(bug|bugfix|fix|defect|hotfix|regression)\b", explicit_text):
        return "bugfix"
    return "feature"

def branch_name(plan, repo_config, jira_key):
    explicit_branch = repo_config.get("branch")
    if explicit_branch:
        return explicit_branch

    suffix = repo_config.get("branch_suffix") or f"{jira_key}-{repo_config['name']}".replace("/","-")
    suffix = str(suffix).strip().lstrip("/")
    return f"{infer_branch_prefix(plan, repo_config)}/{suffix}"

plan=json.loads(sys.argv[1]); i=int(sys.argv[2])
workspace=sys.argv[3]; base=sys.argv[4]; packets=sys.argv[5]; jira=sys.argv[6]; gradle_wrapper=sys.argv[7]
r=plan["repos"][i]
name=r["name"]
local_path=r.get("local_path") or os.path.join(workspace, name.split("/")[-1])
branch=branch_name(plan, r, jira)
packet=os.path.join(packets, f"{name.replace('/','-')}.md")

# Worktree location: sibling folder to repo clone
wt=os.path.join(os.path.dirname(local_path), f"{os.path.basename(local_path)}-{jira}")

print(f"""bash -lc '
set -e
cd "{local_path}"
git fetch origin
git worktree add --no-track -B "{branch}" "{wt}" "origin/{base}" || (echo "worktree add failed"; exit 2)
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
