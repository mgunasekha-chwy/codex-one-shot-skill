# one-shot-this Skill Description

Last verified: 2026-06-08

## Why this document exists
- This file helps future agents and developers decide whether this repository is the right place to change the `one-shot-this` Codex skill and which files shape its behavior.
- It complements `SKILL.md` by summarizing ownership, workflow boundaries, and change impact rather than restating every instruction.

## Repository in one paragraph
- This repository owns a Codex skill that turns a Jira issue into a coordinated multi-repo implementation workflow. The skill gathers requirements from Jira, uses the service catalog to identify impacted repositories, asks the user to approve a structured plan, then generates per-repo work packets and spawns one Codex worker per repo in tmux-backed git worktrees.

## Primary entry points
- `SKILL.md`: canonical user-facing workflow, approval gates, worker rules, and branch naming behavior.
- `agents/openai.yaml`: skill metadata that disables implicit invocation.
- `scripts/write_work_packets.py`: converts approved plan JSON into one markdown packet per target repo.
- `scripts/spawn_tmux_worktrees.sh`: creates worktrees, opens the tmux session, seeds Gradle helper state, and starts Codex workers.
- `scripts/codex-gradle-test.sh`: wrapper for running Gradle commands inside worktrees with a stable `GRADLE_USER_HOME` and `-Pgit.root=...`.

## What this repository owns
- The orchestration contract for a Jira-driven, multi-repo change workflow.
- The packet format handed to spawned workers, including testing and push/PR constraints.
- The tmux and git-worktree setup logic used to isolate one Codex worker per impacted repository.
- Gradle worktree compatibility behavior for repos that use `./gradlew`.

## Core runtime flow
1. The skill reads a Jira issue and extracts requirements, acceptance criteria, and related context.
2. It uses the service catalog to identify likely impacted repositories and produces a per-repo implementation plan.
3. After explicit user approval, `scripts/write_work_packets.py` writes one markdown packet per repo from the approved plan JSON.
4. `scripts/spawn_tmux_worktrees.sh` creates a tmux session, adds one worktree per repo from `origin/<base-branch>`, and starts a Codex session in each pane.
5. For Gradle repos, the launcher copies `scripts/codex-gradle-test.sh` into the worktree and verifies the wrapper before the worker starts.
6. Each worker operates only in its assigned repo, runs the packet’s tests, and must ask before pushing or opening a PR.

## Downstream systems and purpose
- Jira MCP: source of issue requirements and metadata used to build the plan.
- service-catalog MCP: source of impacted repo discovery and dependency/context lookup.
- Local git clones: required so the launcher can create worktrees beside each repo.
- `tmux`: hosts the parallel worker session.
- `codex`: started inside each tmux pane as the worker runtime.
- Gradle tooling: used only when a target repo has `./gradlew`, to avoid worktree-specific Nebula/Grgit failures.

## Internal modules to read first
- [SKILL.md](/Users/csaba/Desktop/code/codex-one-shot-skill/SKILL.md)
- [scripts/spawn_tmux_worktrees.sh](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/spawn_tmux_worktrees.sh)
- [scripts/write_work_packets.py](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/write_work_packets.py)
- [scripts/codex-gradle-test.sh](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/codex-gradle-test.sh)

## Reliability or edge behavior
- The skill has an explicit approval gate before any packets are generated or workers are spawned.
- The launcher canonicalizes the plan and packets paths so callers can pass relative paths safely.
- If `${SHELL}` is invalid, the launcher falls back to `/bin/bash`.
- The launcher pre-creates a shared `.gradle-user-home` under `WORKSPACE_ROOT` and seeds `gradle.properties` from `~/.gradle/gradle.properties` when available.
- The Gradle wrapper always resolves the git common dir and passes `-Pgit.root=<repo-root>` to keep worktree-based builds stable.
- The launcher exits early when required tools, helper scripts, plan files, packets, or tmux session names are invalid or already in use.

## What usually changes together
- Changes to the workflow contract in `SKILL.md` often require matching updates to packet generation in `scripts/write_work_packets.py`.
- Branch naming or worker constraints usually affect both `SKILL.md` and the Python packet template logic.
- Worktree spawn behavior, shell setup, or Gradle handling usually affect both `scripts/spawn_tmux_worktrees.sh` and `scripts/codex-gradle-test.sh`.
- If the expected plan JSON shape changes, both helper scripts must stay in sync.

## How to keep this document evolving
- Update this file when the skill workflow, approval gates, packet schema, worker constraints, required tools, or repo discovery/test behavior changes.
- Remove or revise any integration listed here if Jira access, service catalog usage, tmux orchestration, or Gradle worktree handling changes in code or instructions.
