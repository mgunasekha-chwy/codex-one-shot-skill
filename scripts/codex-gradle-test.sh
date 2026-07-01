#!/usr/bin/env bash
set -euo pipefail

export GRADLE_USER_HOME="${CODEX_SHARED_GRADLE_USER_HOME:-${PWD}/.gradle-user-home}"
mkdir -p "${GRADLE_USER_HOME}"
GIT_COMMON_DIR="$(git rev-parse --git-common-dir)"
GIT_ROOT="$(cd "${GIT_COMMON_DIR}/.." && pwd)"

if [[ -n "${CODEX_GRADLE_JAVA_HOME:-}" ]]; then
  if [[ ! -x "${CODEX_GRADLE_JAVA_HOME}/bin/java" ]]; then
    echo "Configuration error: CODEX_GRADLE_JAVA_HOME does not contain an executable bin/java: ${CODEX_GRADLE_JAVA_HOME}" >&2
    exit 2
  fi
  export JAVA_HOME="${CODEX_GRADLE_JAVA_HOME}"
  export PATH="${JAVA_HOME}/bin:${PATH}"
fi

./gradlew -Pgit.root="${GIT_ROOT}" "$@"
