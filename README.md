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

Given a Jira issue key, the skill fetches requirements from Jira, identifies likely impacted repositories via the service catalog, produces a per-repo implementation plan, asks for approval, and then starts a paper-trailed implement/review workflow.

The paper trail is organized as:

- `<JIRA_KEY>/`
- `<JIRA_KEY>/workflow-<UUID>/`
- `<JIRA_KEY>/workflow-<UUID>/iteration-###/`

Implementation spawns one Codex worker per affected repo. Review spawns one Codex reviewer process that scans all affected repos for that workflow iteration, accepts optional custom feedback, and produces a revised implement plan when another iteration is needed.

## When To Use It

- You have a Jira issue and need to coordinate changes across one or more repositories.
- You want a repeatable workflow for repo selection, planning, implementation, review, and follow-up implementation iterations.
- You want `tmux` worktrees, per-repo implementation packets, consolidated review packets, and durable paper-trail manifests generated automatically.
- You want review feedback to accelerate the next `implement -> review` cycle instead of requiring a separate manual replanning step.

## Repository Structure

- `SKILL.md`: canonical skill instructions and workflow
- `agents/openai.yaml`: UI metadata for the skill
- `scripts/`: helper scripts for workflow/iteration manifests, packet generation, tmux setup, review setup, and Gradle test execution

## Notes

- The tmux launcher copies `scripts/codex-gradle-test.sh` only for worktrees that contain `./gradlew`.
- Workflow worktrees are reused across iterations and are named with the Jira key plus workflow UUID prefix to avoid same-ticket collisions.
- Review is intentionally consolidated into one Codex process so cross-repo consistency is evaluated in one pass.
- Review can be invoked with custom text, for example `$one-shot-this AGC-126 review "Custom review feedback that should be addressed"`.
- When review finds blocking issues, it writes `reviews/next_implement_plan.json` and asks in the review tmux session before spawning the next implementation workers.
- The launcher uses `${SHELL}` when present instead of assuming Bash.
- For Gradle repos, spawned worktrees should use the user's normal Gradle configuration from `~/.gradle` by default.
- A workspace-specific Gradle configuration may override the default when the launched workspace intentionally provides one.
- The Gradle wrapper helper exists to make Gradle work safely from git worktrees; it should not require machine-specific tuning to use this skill.
- This repo should live at `~/.codex/skills/one-shot-this` unless you manage your Codex skills directory differently.

## Canonical Documentation

See [SKILL.md](./SKILL.md) for the full workflow and operating rules.

This README is intentionally brief so `SKILL.md` remains the single source of truth.
