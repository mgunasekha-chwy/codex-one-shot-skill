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
GRADLE_PREFLIGHT_ARGS="${CODEX_GRADLE_PREFLIGHT_ARGS:-compileJava}"

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

print_gradle_failure_guidance() {
  local output="$1"
  echo "Fix the local Java/Gradle/repo configuration before starting Codex workers for this change." >&2

  if [[ "$output" == *"CODEX_GRADLE_JAVA_HOME does not contain an executable bin/java"* ]]; then
    echo "The configured CODEX_GRADLE_JAVA_HOME is invalid. Point it at a JDK directory that contains bin/java." >&2
  elif [[ "$output" == *"Unsupported class file major version"* ]]; then
    echo "Detected Java bytecode/tooling that this Gradle version cannot parse." >&2
    echo "This commonly means a newer Java is running with an older Gradle wrapper." >&2
  elif [[ "$output" == *"invalid source release"* || "$output" == *"release version"* || "$output" == *"not supported"* ]]; then
    echo "Detected a Java source/release level that the active JDK does not support." >&2
  elif [[ "$output" == *"No matching toolchains"* || "$output" == *"No locally installed toolchains match"* ]]; then
    echo "Detected a missing Gradle Java toolchain for this repo." >&2
  fi

  echo "Ask the user for the correct JDK path when needed, then retry with an explicit Java home." >&2
  echo "For mixed-JDK multi-repo plans, set repos[].gradle_java_home in the plan JSON." >&2
  echo "A global fallback is still supported with CODEX_GRADLE_JAVA_HOME=/path/to/jdk." >&2
  echo "Override the preflight command only when necessary with CODEX_GRADLE_PREFLIGHT_ARGS." >&2
}

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/codex-preflight.XXXXXX")"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

declare -a GRADLE_REPO_PATHS=()
declare -a GRADLE_REPO_JAVA_HOMES=()
declare -a GRADLE_OUTPUT_FILES=()
declare -a GRADLE_PIDS=()
declare -a GRADLE_STATUSES=()

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
gradle_java_home = repo.get("gradle_java_home") or plan.get("gradle_java_home") or ""
print(local_path)
print(packet_name)
print(gradle_java_home)
PY
)"
  local_path="$(printf '%s\n' "$repo_info" | sed -n '1p')"
  packet_name="$(printf '%s\n' "$repo_info" | sed -n '2p')"
  gradle_java_home="$(printf '%s\n' "$repo_info" | sed -n '3p')"
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

    GRADLE_REPO_PATHS+=("$local_path")
    GRADLE_REPO_JAVA_HOMES+=("$gradle_java_home")
  fi
done

for ((i=0; i<${#GRADLE_REPO_PATHS[@]}; i++)); do
  local_path="${GRADLE_REPO_PATHS[$i]}"
  gradle_java_home="${GRADLE_REPO_JAVA_HOMES[$i]}"
  output_file="${TMP_DIR}/gradle-${i}.log"
  GRADLE_OUTPUT_FILES+=("$output_file")

  echo "Running Gradle preflight for ${local_path}: ./.codex-gradle-test.sh ${GRADLE_PREFLIGHT_ARGS}" >&2
  (
    cd "$local_path"
    export CODEX_SHARED_GRADLE_USER_HOME="$SHARED_GRADLE_USER_HOME"
    if [[ -n "$gradle_java_home" ]]; then
      export CODEX_GRADLE_JAVA_HOME="$gradle_java_home"
    fi
    # shellcheck disable=SC2086
    ./.codex-gradle-test.sh $GRADLE_PREFLIGHT_ARGS
  ) >"$output_file" 2>&1 &
  GRADLE_PIDS+=("$!")
done

preflight_failed=0
for ((i=0; i<${#GRADLE_PIDS[@]}; i++)); do
  if ! wait "${GRADLE_PIDS[$i]}"; then
    GRADLE_STATUSES[$i]=1
    preflight_failed=1
  else
    GRADLE_STATUSES[$i]=0
  fi
done

for ((i=0; i<${#GRADLE_REPO_PATHS[@]}; i++)); do
  local_path="${GRADLE_REPO_PATHS[$i]}"
  output_file="${GRADLE_OUTPUT_FILES[$i]}"
  preflight_output="$(cat "$output_file")"
  if [[ -n "$preflight_output" ]]; then
    printf '%s\n' "$preflight_output" >&2
  fi
done

if [[ "$preflight_failed" -ne 0 ]]; then
  for ((i=0; i<${#GRADLE_REPO_PATHS[@]}; i++)); do
    if [[ "${GRADLE_STATUSES[$i]}" -eq 0 ]]; then
      continue
    fi
    output_file="${GRADLE_OUTPUT_FILES[$i]}"
    if [[ -s "$output_file" ]]; then
      preflight_output="$(cat "$output_file")"
    else
      preflight_output=""
    fi
    local_path="${GRADLE_REPO_PATHS[$i]}"
    echo "Configuration error: Gradle preflight failed for ${local_path}." >&2
    print_gradle_failure_guidance "$preflight_output"
  done
  exit 2
fi

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
