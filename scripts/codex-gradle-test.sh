#!/usr/bin/env bash
set -euo pipefail

export GRADLE_USER_HOME="${PWD}/.gradle-user-home"
GIT_COMMON_DIR="$(git rev-parse --git-common-dir)"
GIT_ROOT="$(cd "${GIT_COMMON_DIR}/.." && pwd)"

./gradlew -Pgit.root="${GIT_ROOT}" "$@"
