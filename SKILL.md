---
name: one-shot-this
description: |
  Explicit skill. Given a Jira issue key, fetch requirements via Jira MCP, identify impacted repos via service-catalog MCP,
  produce a per-repo implementation plan, ask for approval, then run a single-repo handoff in the current terminal or
  spawn one Codex worker per repo in tmux panes for multi-repo changes.
---

# Workflow (must follow exactly)

## Inputs
- Jira story key (e.g., CON-7134)
- Environment variables (if set):
  - WORKSPACE_ROOT: folder that contains local clones of repos (default: current directory)
  - BASE_BRANCH: default base branch for worktrees (default: main)
  - CODEX_GRADLE_PREFLIGHT_ARGS: Gradle preflight args for repos with ./gradlew (default: compileJava)
  - CODEX_GRADLE_JAVA_HOME: explicit global JDK home for Gradle preflight and worker Gradle commands

## Step 1 — Requirements intake (read-only)
1) Use Jira MCP to fetch:
   - title, description, acceptance criteria, links, attachments
2) Summarize requirements and list assumptions/questions.

## Step 2 — Repo selection using service catalog (read-only)
1) Use service-catalog MCP to find impacted repos/services.
2) Produce a list of repos with:
   - why impacted
   - key modules/files likely touched
   - integration/dependency notes

## Step 3 — Plan
Output a structured plan with:
- jira_key
- issue_type and/or title when known, so branch type can be inferred
- repos: list of { name, local_path (if known), branch_suffix, branch_type (optional), steps[], tests[], rollout_notes }
- cross_repo_steps (if any)
Then ask for approval:
"Approve to generate work packets and start the repo workflow?"

STOP if not approved.

## Step 4 — Generate work packets + run the repo workflow
1) Run scripts/write_work_packets.py to write one markdown packet per repo into ./run/packets/
2) If the approved plan has exactly one repo:
   - Run `scripts/preflight_repo_change.sh <JIRA_KEY> <plan.json> <packets_dir> single`
   - This validates required commands, repo paths, packet paths, git status, and Gradle configuration before handoff.
   - If preflight fails, stop immediately and report the configuration error to the user.
   - If preflight succeeds, final response for this step must be the exact `codex -C ...` command printed by the helper.
   - The user runs that command in the current terminal to start a fresh Codex session/context for the repo.
3) If the approved plan has more than one repo, run scripts/spawn_tmux_worktrees.sh to:
   - run shared preflight before any tmux panes are created
   - create a worktree per repo
   - open a tmux session with one pane per repo
   - start a Codex session in each pane, feeding it the repo’s packet
   - note: the launcher canonicalizes `<plan.json>` and `<packets_dir>` to absolute paths, so callers can pass relative paths safely
4) After spawn succeeds, do not run extra tmux verification commands.
5) Final response for the multi-repo path must be a single instruction line:
   - `tmux attach -t codex-<JIRA_KEY>`

## Worker rules (each spawned Codex session)
- Operate only within its assigned repo or worktree.
- Implement per packet.
- Run tests listed in the packet.
- Branch naming defaults to `feature/<branch_suffix>`. Use `bugfix/<branch_suffix>` only when the story explicitly indicates a bug fix or the plan sets `branch_type: bugfix`.
- Before any push or PR, explicitly ask:
  "Approve push + PR for <repo>?"
- If approved:
  - ensure the current local branch tracks `origin/<current-branch>` (do not only check that some upstream exists)
  - if tracking is missing or points elsewhere (for example `origin/main`), set/fix it by pushing with upstream tracking (for example `git push -u origin <branch>`)
  - create PR (prefer gh; otherwise print the exact manual command)
- Report back with:
  - branch name
  - PR link
  - tests run + results
  - any follow-ups/risks

## Gradle reliability and fail-fast preflight
- For repos that use Gradle, run Gradle commands via `./.codex-gradle-test.sh` when the helper is present.
- Preflight defaults to `./.codex-gradle-test.sh compileJava` so Java, Gradle, plugin, buildscript, and main-source compilation errors fail before Codex workers start.
- The Gradle helper must not scan Gradle files, wrapper properties, or installed JDKs to guess a Java version.
- By default, use the environment inherited from the shell that launched the skill.
- If a plan repo supplies `gradle_java_home`, use that JDK for that repo's Gradle preflight and worker commands.
- If the user supplies `CODEX_GRADLE_JAVA_HOME`, use it as a global fallback for Gradle repos without `gradle_java_home`.
- Explicit Java selection is Gradle-scoped only: the helper sets `JAVA_HOME` and prepends `$JAVA_HOME/bin` in the helper process.
- Known example: `Unsupported class file major version 65` commonly means Java 21 is running with an older Gradle wrapper; ask the user for the correct JDK path, often Java 17 for Gradle 7.x repos that target Java 17.
- Use `CODEX_GRADLE_PREFLIGHT_ARGS` only when a repo needs a different safe preflight command.
- If preflight fails, stop immediately, notify the user that local Java/Gradle/repo configuration must be fixed, and ask for the correct `CODEX_GRADLE_JAVA_HOME` before retrying.
- Never spawn tmux workers when Gradle preflight fails.
- For multi-repo plans, run Gradle preflight checks in parallel before creating tmux workers.
- The launcher and preflight helper only copy the Gradle wrapper helper when the repo or worktree contains `./gradlew`.
- The launcher uses `${SHELL}` when present instead of assuming Bash.
- Gradle runs should use the user's normal Gradle configuration from `~/.gradle` by default, but explicit Java selection is scoped to the helper process and must not modify the user's shell.
- A workspace-local Gradle configuration may override the default when the launched workspace intentionally provides one.
- This wrapper exists to make Gradle run safely from repos and git worktrees and always passes `-Pgit.root=<repo-root>` to avoid `nebula.release`/`grgit` failures like `.../config (Is a directory)`.
- If a Gradle-based packet lists `./gradlew test --tests ...`, execute the same arguments via `./.codex-gradle-test.sh` instead.
