# one-shot-this Skill Description

Last verified: 2026-06-08

## Why this document exists
- This file helps future agents and developers decide whether this repository is the right place to change the `one-shot-this` Codex skill and which files shape its behavior.
- It complements `SKILL.md` by summarizing ownership, workflow boundaries, and change impact rather than restating every instruction.

## Repository in one paragraph
- This repository owns a Codex skill that turns a Jira issue into a coordinated multi-repo implement/review loop. The skill gathers requirements from Jira, uses the service catalog to identify impacted repositories, asks the user to approve a structured plan, creates a durable paper trail, spawns implementation workers in tmux-backed git worktrees, and then supports consolidated review that can convert findings and custom user feedback into the next implementation plan.

## Primary entry points
- `SKILL.md`: canonical user-facing workflow, approval gates, paper-trail layout, worker rules, and review rules.
- `agents/openai.yaml`: skill metadata that disables implicit invocation.
- `scripts/init_workflow.py`: creates `<JIRA_KEY>/workflow-<UUID>/iteration-001/` and initializes manifests.
- `scripts/next_iteration.py`: creates the next `iteration-###` inside an existing workflow.
- `scripts/write_work_packets.py`: converts an approved plan and prior review findings into one implementation packet per repo.
- `scripts/write_review_packet.py`: creates one consolidated review packet for all affected repos in an iteration, including optional custom review feedback and next-plan handoff instructions.
- `scripts/spawn_tmux_worktrees.sh`: creates or safely reuses repo worktrees, opens the implementation tmux session, seeds Gradle helper state, and starts Codex workers.
- `scripts/spawn_review_tmux.sh`: validates recorded worktrees and starts one consolidated Codex review process.
- `scripts/codex-gradle-test.sh`: wrapper for running Gradle commands inside worktrees with a stable `GRADLE_USER_HOME` and `-Pgit.root=...`.

## What this repository owns
- The orchestration contract for a Jira-driven, multi-repo implement/review workflow.
- The ticket/workflow/iteration paper-trail schema.
- The packet formats handed to implementation and review workers, including review-driven next implementation plans.
- The tmux and git-worktree setup logic used to isolate implementation workers and support consolidated review.
- Gradle worktree compatibility behavior for repos that use `./gradlew`.

## Core runtime flow
1. `implement <JIRA_KEY>` reads Jira requirements, discovers impacted repos, and asks the user to approve a structured plan.
2. The skill creates `<JIRA_KEY>/workflow-<UUID>/iteration-001/`, stores manifests, writes per-repo implementation packets, and spawns one Codex worker per repo.
3. `review <JIRA_KEY>` or `review <workflow-dir>` can include custom quoted feedback, generates one consolidated review packet, and spawns one Codex reviewer process to inspect all affected repos.
4. If review finds issues, the reviewer writes `reviews/review.md` and `reviews/next_implement_plan.json`, asks for approval inside the review tmux session, then creates the next iteration and spawns implementation workers when approved.
5. The loop repeats as `implement -> review -> implement -> review` until the consolidated review output is acceptable, with each review teaching the next implementation iteration what not to repeat.
6. Each worker must ask before pushing or opening a PR.

## Downstream systems and purpose
- Jira MCP: source of issue requirements and metadata used to build the plan.
- service-catalog MCP: source of impacted repo discovery and dependency/context lookup.
- Local git clones: required so the launcher can create worktrees beside each repo.
- `tmux`: hosts implementation worker sessions and the consolidated review session.
- `codex`: started inside each tmux pane as the worker runtime.
- Gradle tooling: used only when a target repo has `./gradlew`, to avoid worktree-specific Nebula/Grgit failures.

## Internal modules to read first
- [SKILL.md](/Users/csaba/Desktop/code/codex-one-shot-skill/SKILL.md)
- [scripts/paper_trail.py](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/paper_trail.py)
- [scripts/write_work_packets.py](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/write_work_packets.py)
- [scripts/write_review_packet.py](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/write_review_packet.py)
- [scripts/spawn_tmux_worktrees.sh](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/spawn_tmux_worktrees.sh)
- [scripts/spawn_review_tmux.sh](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/spawn_review_tmux.sh)
- [scripts/codex-gradle-test.sh](/Users/csaba/Desktop/code/codex-one-shot-skill/scripts/codex-gradle-test.sh)

## Reliability or edge behavior
- Workflow creation retries UUID generation if a workflow directory collision occurs.
- Review feedback is stored as `iteration-###/reviews/user_feedback.md` when provided, and the next implementation plan path is tracked as `iteration-###/reviews/next_implement_plan.json`.
- Worktree paths include the Jira key and workflow UUID prefix so the same ticket can have multiple independent workflow attempts.
- Existing compatible worktrees are reused; incompatible paths fail clearly before workers start.
- The launchers canonicalize workflow and iteration paths so callers can pass relative paths safely.
- If `${SHELL}` is invalid, launchers fall back to `/bin/bash`.
- The implementation launcher pre-creates a shared `.gradle-user-home` under the workflow workspace root and seeds `gradle.properties` from `~/.gradle/gradle.properties` when available.
- The Gradle wrapper always resolves the git common dir and passes `-Pgit.root=<repo-root>` to keep worktree-based builds stable.

## What usually changes together
- Changes to the workflow contract in `SKILL.md` usually require matching updates to packet generation and launcher scripts.
- Paper-trail schema changes usually affect `scripts/paper_trail.py`, packet writers, launchers, and tests.
- Branch naming or worker constraints usually affect both `SKILL.md` and `scripts/write_work_packets.py`.
- Worktree spawn behavior, shell setup, or Gradle handling usually affects `scripts/spawn_tmux_worktrees.sh` and sometimes `scripts/codex-gradle-test.sh`.

## How to keep this document evolving
- Update this file when the skill workflow, paper-trail schema, approval gates, packet schema, worker constraints, required tools, or repo discovery/test behavior changes.
- Remove or revise any integration listed here if Jira access, service catalog usage, tmux orchestration, review behavior, or Gradle worktree handling changes in code or instructions.
