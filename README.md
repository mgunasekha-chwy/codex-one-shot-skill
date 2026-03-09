# one-shot-this

This repository contains the `one-shot-this` Codex skill.

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

## Canonical Documentation

See [SKILL.md](./SKILL.md) for the full workflow and operating rules.

This README is intentionally brief so `SKILL.md` remains the single source of truth.
