# one-shot-this Skill Description

Last verified: 2026-06-08

## Why this document exists
- This file helps future agents and developers decide whether this repository is the right place to change the `one-shot-this` Codex skill and which files shape its behavior.
- It complements `SKILL.md` by summarizing ownership, workflow boundaries, and change impact rather than restating every instruction.

## Repository in one paragraph
- This repository owns a Codex skill that turns a Jira issue into a coordinated repo implementation workflow. The skill gathers requirements from Jira, uses the service catalog to identify impacted repositories, asks the user to approve a structured plan, then generates per-repo work packets. Single-repo plans hand off to a fresh Codex session in the current terminal; multi-repo plans spawn one Codex worker per repo in tmux-backed git worktrees.

## Primary entry points
- `SKILL.md`: canonical user-facing workflow, approval gates, worker rules, and branch naming behavior.
- `agents/openai.yaml`: skill metadata that disables implicit invocation.
- `scripts/write_work_packets.py`: converts approved plan JSON into one markdown packet per target repo.
- `scripts/preflight_repo_change.sh`: validates tools, repo paths, packet paths, git state, and Gradle configuration before handoff.
- `scripts/spawn_tmux_worktrees.sh`: creates worktrees, opens the tmux session, seeds Gradle helper state, and starts Codex workers.
- `scripts/codex-gradle-test.sh`: wrapper for running Gradle commands inside worktrees with a stable `GRADLE_USER_HOME` and `-Pgit.root=...`.

## What this repository owns
- The orchestration contract for a Jira-driven, multi-repo change workflow.
- The packet format handed to spawned workers, including testing and push/PR constraints.
- The single-repo current-terminal handoff and multi-repo tmux/git-worktree setup logic.
- Gradle compatibility, optional per-repo wrapper-scoped Java selection, and fail-fast preflight behavior for repos that use `./gradlew`.

## Core runtime flow
1. The skill reads a Jira issue and extracts requirements, acceptance criteria, and related context.
2. It uses the service catalog to identify likely impacted repositories and produces a per-repo implementation plan.
3. After explicit user approval, `scripts/write_work_packets.py` writes one markdown packet per repo from the approved plan JSON.
4. `scripts/preflight_repo_change.sh` validates the local repo setup and runs Gradle preflight for repos with `./gradlew`.
5. For a single-repo plan, the helper prints the exact `codex -C ...` command for a fresh current-terminal session.
6. For a multi-repo plan, `scripts/spawn_tmux_worktrees.sh` creates a tmux session, adds one worktree per repo from `origin/<base-branch>`, and starts a Codex session in each pane.
7. Each worker operates only in its assigned repo or worktree, runs the packet’s tests, and must ask before pushing or opening a PR.

## Downstream systems and purpose
- Jira MCP: source of issue requirements and metadata used to build the plan.
- service-catalog MCP: source of impacted repo discovery and dependency/context lookup.
- Local git clones: required so the launcher can create worktrees beside each repo.
- `tmux`: hosts the parallel worker session for multi-repo changes.
- `codex`: started inside each tmux pane as the worker runtime.
- Gradle tooling: used only when a target repo has `./gradlew`, to fail fast on Java/build configuration problems, honor optional per-repo or global Java overrides, and avoid Nebula/Grgit failures.

## Internal modules to read first
- [SKILL.md](/Users/csaba/Desktop/code/codex-one-shot-skill/SKILL.md)
- [scripts/preflight_repo_change.sh](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/preflight_repo_change.sh)
- [scripts/spawn_tmux_worktrees.sh](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/spawn_tmux_worktrees.sh)
- [scripts/write_work_packets.py](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/write_work_packets.py)
- [scripts/codex-gradle-test.sh](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/codex-gradle-test.sh)

## Reliability or edge behavior
- The skill has an explicit approval gate before any packets are generated or workers are spawned.
- The helper scripts canonicalize plan and packets paths so callers can pass relative paths safely.
- If `${SHELL}` is invalid, the launcher falls back to `/bin/bash`.
- The preflight helper pre-creates a shared `.gradle-user-home` under `WORKSPACE_ROOT` and seeds `gradle.properties` from `~/.gradle/gradle.properties` when available.
- Gradle preflight defaults to `compileJava` and runs in parallel for multi-repo plans before tmux workers are created.
- The Gradle wrapper always resolves the git common dir and passes `-Pgit.root=<repo-root>` to keep repo and worktree builds stable.
- Gradle Java selection defaults to the launcher shell environment, can be set per repo with `gradle_java_home`, and can fall back to global `CODEX_GRADLE_JAVA_HOME`.
- Explicit Gradle Java selection is scoped to the helper process and does not change the user's shell environment.
- The helper does not scan Gradle files or installed JDKs; if preflight fails with a known Java/Gradle mismatch, the controlling Codex session asks the user for the correct JDK path before retrying.
- The preflight helper exits early when required tools, helper scripts, plan files, packets, repo paths, or Gradle configuration are invalid.
- The tmux launcher still exits early when tmux session names are invalid or already in use.

## What usually changes together
- Changes to the workflow contract in `SKILL.md` often require matching updates to packet generation in `scripts/write_work_packets.py`.
- Branch naming or worker constraints usually affect both `SKILL.md` and the Python packet template logic.
- Preflight, worktree spawn behavior, shell setup, Java selection, or Gradle handling usually affect `scripts/preflight_repo_change.sh`, `scripts/spawn_tmux_worktrees.sh`, and `scripts/codex-gradle-test.sh`.
- If the expected plan JSON shape changes, both helper scripts must stay in sync.

## How to keep this document evolving
- Update this file when the skill workflow, approval gates, packet schema, worker constraints, required tools, preflight behavior, or repo discovery/test behavior changes.
- Remove or revise any integration listed here if Jira access, service catalog usage, tmux orchestration, or Gradle worktree handling changes in code or instructions.
