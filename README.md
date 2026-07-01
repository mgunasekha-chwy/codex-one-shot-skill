# one-shot-this

This repository contains the `one-shot-this` Codex skill.

## Install

This repo is currently meant to be installed manually rather than via the GitHub skill installer.

Clone it into your Codex skills directory with the skill folder name `one-shot-this`:

```bash
git clone git@github.com:mgunasekha-chwy/one-shot-this.git ~/.codex/skills/one-shot-this
```

If you prefer HTTPS:

```bash
git clone https://github.com/mgunasekha-chwy/one-shot-this.git ~/.codex/skills/one-shot-this
```

Then restart Codex so it reloads skills.

## Requirements

The machine running this skill needs:

- `codex`
- `git`
- `tmux` for multi-repo changes
- `python3`
- local clones of the repos you want the workers to operate on
- Jira MCP access
- service-catalog MCP access

Optional environment variables:

- `WORKSPACE_ROOT`: folder containing local repo clones; defaults to the current directory
- `BASE_BRANCH`: branch used when creating worktrees; defaults to `main`
- `CODEX_GRADLE_PREFLIGHT_ARGS`: Gradle preflight args for repos with `./gradlew`; defaults to `compileJava`
- `CODEX_GRADLE_JAVA_HOME`: explicit global JDK home used by Gradle preflight and worker Gradle commands

## What It Does

Given a Jira issue key, the skill fetches requirements from Jira, identifies likely impacted repositories via the service catalog, produces a per-repo implementation plan, asks for approval, and then starts the right repo workflow. A single-repo plan prints an exact `codex -C ...` command for a fresh Codex session in the current terminal. A multi-repo plan spawns one Codex worker per repo in tmux worktrees.

## When To Use It

- You have a Jira issue and need to coordinate changes across one or more repositories.
- You want a repeatable workflow for repo selection, planning, preflight validation, and implementation handoff.
- You want single-repo work to stay in the current terminal with fresh Codex context.
- You want multi-repo `tmux` worktrees and per-repo work packets generated automatically.

## Repository Structure

- `SKILL.md`: canonical skill instructions and workflow
- `agents/openai.yaml`: UI metadata for the skill
- `scripts/`: helper scripts for packet generation, preflight validation, tmux setup, and Gradle test execution

## Notes

- The preflight helper fails fast when required commands, repo paths, packet paths, git state, or Gradle configuration are invalid.
- For single-repo plans, the preflight helper prints the fresh `codex -C ...` command to run in the current terminal.
- The tmux launcher copies `scripts/codex-gradle-test.sh` only for worktrees that contain `./gradlew`.
- The launcher uses `${SHELL}` when present instead of assuming Bash.
- For Gradle repos, preflight and spawned worktrees should use the user's normal shell and Gradle configuration by default.
- The Gradle helper uses per-repo `gradle_java_home` plan entries when present, or `CODEX_GRADLE_JAVA_HOME` as a global fallback; it does not scan the machine for installed JDKs.
- Multi-repo Gradle preflight runs checks in parallel before any tmux workers are spawned.
- If Gradle preflight hits a Java/Gradle mismatch, no tmux workers are spawned. The controlling Codex session should ask for the correct JDK path and retry, for example with Java 17 for older Gradle 7.x repos.
- A workspace-specific Gradle configuration may override the default when the launched workspace intentionally provides one.
- The Gradle wrapper helper exists to make Gradle work safely from normal repos and git worktrees; it should not require machine-specific tuning to use this skill.
- This repo should live at `~/.codex/skills/one-shot-this` unless you manage your Codex skills directory differently.

## Canonical Documentation

See [SKILL.md](./SKILL.md) for the full workflow and operating rules.

This README is intentionally brief so `SKILL.md` remains the single source of truth.
