#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: preflight_repo_change.sh JIRA-123 <plan.json> <packets_dir> <single|multi>" >&2
}

JIRA_KEY="${1:-}"
PLAN_JSON="${2:-}"
PACKETS_DIR="${3:-}"
MODE="${4:-}"

if [[ -z "$JIRA_KEY" || -z "$PLAN_JSON" || -z "$PACKETS_DIR" || -z "$MODE" ]]; then
  usage
  exit 2
fi

if [[ "$MODE" != "single" && "$MODE" != "multi" ]]; then
  echo "Invalid mode: ${MODE}. Expected single or multi." >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRADLE_WRAPPER_SOURCE="${SCRIPT_DIR}/codex-gradle-test.sh"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-$(pwd)}"
SHARED_GRADLE_USER_HOME="${CODEX_SHARED_GRADLE_USER_HOME:-${WORKSPACE_ROOT}/.gradle-user-home}"
DEFAULT_GRADLE_PROPERTIES_SOURCE="${HOME}/.gradle/gradle.properties"
GRADLE_PREFLIGHT_ARGS="${CODEX_GRADLE_PREFLIGHT_ARGS:-help}"

abs_path() {
  local path="$1"
  if [[ -d "$path" ]]; then
    (cd "$path" && pwd)
  else
    (cd "$(dirname "$path")" && printf "%s/%s\n" "$(pwd)" "$(basename "$path")")
  fi
}

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Configuration error: missing required command: $1" >&2
    exit 2
  }
}

PLAN_JSON="$(abs_path "$PLAN_JSON")"
PACKETS_DIR="$(abs_path "$PACKETS_DIR")"

require git
require python3
require codex

if [[ "$MODE" == "multi" ]]; then
  require tmux
fi

if [[ ! -f "$PLAN_JSON" ]]; then
  echo "Configuration error: plan file not found: ${PLAN_JSON}" >&2
  exit 2
fi

if [[ ! -d "$PACKETS_DIR" ]]; then
  echo "Configuration error: packets directory not found: ${PACKETS_DIR}" >&2
  exit 2
fi

if [[ ! -f "$GRADLE_WRAPPER_SOURCE" ]]; then
  echo "Configuration error: missing helper script: ${GRADLE_WRAPPER_SOURCE}" >&2
  exit 2
fi

mkdir -p "$SHARED_GRADLE_USER_HOME"
if [[ -f "$DEFAULT_GRADLE_PROPERTIES_SOURCE" && ! -f "${SHARED_GRADLE_USER_HOME}/gradle.properties" ]]; then
  cp "$DEFAULT_GRADLE_PROPERTIES_SOURCE" "${SHARED_GRADLE_USER_HOME}/gradle.properties"
fi

PLAN_JSON_CONTENT="$(python3 - "$PLAN_JSON" <<'PY'
import json
import sys
with open(sys.argv[1]) as f:
    print(json.dumps(json.load(f)))
PY
)"

repo_count="$(python3 - "$PLAN_JSON_CONTENT" <<'PY'
import json
import sys
plan = json.loads(sys.argv[1])
print(len(plan.get("repos", [])))
PY
)"

if [[ "$repo_count" -lt 1 ]]; then
  echo "Configuration error: plan JSON has no repos[]" >&2
  exit 2
fi

if [[ "$MODE" == "single" && "$repo_count" -ne 1 ]]; then
  echo "Configuration error: single mode requires exactly one repo; plan has ${repo_count}." >&2
  exit 2
fi

if [[ "$MODE" == "multi" && "$repo_count" -lt 2 ]]; then
  echo "Configuration error: multi mode requires at least two repos; plan has ${repo_count}." >&2
  exit 2
fi

for ((i=0; i<repo_count; i++)); do
  repo_info="$(python3 - "$PLAN_JSON_CONTENT" "$i" "$WORKSPACE_ROOT" <<'PY'
import json
import os
import sys
plan = json.loads(sys.argv[1])
i = int(sys.argv[2])
workspace = sys.argv[3]
repo = plan["repos"][i]
name = repo["name"]
local_path = repo.get("local_path") or os.path.join(workspace, name.split("/")[-1])
packet_name = name.replace("/", "-") + ".md"
print(local_path)
print(packet_name)
PY
)"
  local_path="$(printf '%s\n' "$repo_info" | sed -n '1p')"
  packet_name="$(printf '%s\n' "$repo_info" | sed -n '2p')"
  packet_path="${PACKETS_DIR}/${packet_name}"

  if [[ ! -d "$local_path" ]]; then
    echo "Configuration error: repo path not found for plan repo ${i}: ${local_path}" >&2
    exit 2
  fi

  if ! git -C "$local_path" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Configuration error: repo path is not a git work tree: ${local_path}" >&2
    exit 2
  fi

  if [[ ! -f "$packet_path" ]]; then
    echo "Configuration error: packet not found for repo ${i}: ${packet_path}" >&2
    exit 2
  fi

  if [[ -f "${local_path}/gradlew" ]]; then
    cp "$GRADLE_WRAPPER_SOURCE" "${local_path}/.codex-gradle-test.sh"
    chmod +x "${local_path}/.codex-gradle-test.sh"

    echo "Running Gradle preflight for ${local_path}: ./.codex-gradle-test.sh ${GRADLE_PREFLIGHT_ARGS}" >&2
    preflight_output="$(
      {
      cd "$local_path"
      export CODEX_SHARED_GRADLE_USER_HOME="$SHARED_GRADLE_USER_HOME"
      # shellcheck disable=SC2086
      ./.codex-gradle-test.sh $GRADLE_PREFLIGHT_ARGS
      } 2>&1
    )" || {
      printf '%s\n' "$preflight_output" >&2
      echo "Configuration error: Gradle preflight failed for ${local_path}." >&2
      if [[ "$preflight_output" == *"Unsupported class file major version 65"* ]]; then
        echo "Detected Java 21 bytecode/tooling with a Gradle version that cannot parse it." >&2
        echo "This commonly means Java 21 is running with an older Gradle wrapper." >&2
        echo "Ask the user for the correct JDK path, then retry with CODEX_GRADLE_JAVA_HOME=/path/to/jdk." >&2
        echo "For Gradle 7.x repos that target Java 17, retry with CODEX_GRADLE_JAVA_HOME set to a Java 17 JDK." >&2
      fi
      echo "Fix the local Java/Gradle/repo configuration before starting Codex workers for this change." >&2
      echo "Retry with an explicit Java home when needed, for example:" >&2
      if [[ "$MODE" == "multi" ]]; then
        printf '  CODEX_GRADLE_JAVA_HOME=/path/to/jdk bash %q %q %q %q\n' \
          "${SCRIPT_DIR}/spawn_tmux_worktrees.sh" "$JIRA_KEY" "$PLAN_JSON" "$PACKETS_DIR" >&2
      else
        printf '  CODEX_GRADLE_JAVA_HOME=/path/to/jdk bash %q %q %q %q single\n' \
          "${SCRIPT_DIR}/preflight_repo_change.sh" "$JIRA_KEY" "$PLAN_JSON" "$PACKETS_DIR" >&2
      fi
      echo "Override the preflight command only when necessary with CODEX_GRADLE_PREFLIGHT_ARGS." >&2
      exit 2
    }
    printf '%s\n' "$preflight_output" >&2
  fi
done

if [[ "$MODE" == "single" ]]; then
  python3 - "$PLAN_JSON_CONTENT" "$WORKSPACE_ROOT" "$PACKETS_DIR" <<'PY'
import json
import os
import shlex
import sys

plan = json.loads(sys.argv[1])
workspace = sys.argv[2]
packets_dir = sys.argv[3]
repo = plan["repos"][0]
name = repo["name"]
local_path = repo.get("local_path") or os.path.join(workspace, name.split("/")[-1])
packet_path = os.path.join(packets_dir, name.replace("/", "-") + ".md")
print("Preflight succeeded.")
print("Start a fresh Codex session in the current terminal with:")
print(f"codex -C {shlex.quote(local_path)} \"$(cat {shlex.quote(packet_path)})\"")
PY
else
  echo "Preflight succeeded for ${repo_count} repos."
fi
