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
- `tmux`
- `python3`
- local clones of the repos you want the workers to operate on
- Jira MCP access
- service-catalog MCP access

Optional environment variables:

- `WORKSPACE_ROOT`: folder containing local repo clones; defaults to the current directory
- `BASE_BRANCH`: branch used when creating worktrees; defaults to `main`

## What It Does

Given a Jira issue key, the skill fetches requirements from Jira, identifies likely impacted repositories via the service catalog, produces a per-repo implementation plan, asks for approval, and then spawns one Codex worker per repo in tmux worktrees.

## When To Use It

- You have a Jira issue and need to coordinate changes across one or more repositories.
- You want a repeatable workflow for repo selection, planning, and parallel worker setup.
- You want `tmux` worktrees and per-repo work packets generated automatically.

## Repository Structure

- `SKILL.md`: canonical skill instructions and workflow
- `agents/openai.yaml`: UI metadata for the skill
- `scripts/`: helper scripts for packet generation, tmux setup, and Gradle test execution

## Notes

- The tmux launcher copies `scripts/codex-gradle-test.sh` only for worktrees that contain `./gradlew`.
- This repo should live at `~/.codex/skills/one-shot-this` unless you manage your Codex skills directory differently.

## Canonical Documentation

See [SKILL.md](./SKILL.md) for the full workflow and operating rules.

This README is intentionally brief so `SKILL.md` remains the single source of truth.
