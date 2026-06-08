---
name: one-shot-this
description: |
  Explicit skill. Given a Jira issue key, orchestrate a paper-trailed implement/review loop across impacted repos using Jira MCP,
  service-catalog MCP, git worktrees, tmux workers, and per-iteration artifacts.
---

# Workflow (must follow exactly)

## Inputs
- Mode and target:
  - `implement <JIRA_KEY>` starts a new workflow attempt for that Jira ticket.
  - `implement <WORKFLOW_DIR>` creates the next implementation iteration for an existing workflow.
  - `review <JIRA_KEY> [CUSTOM_FEEDBACK]` finds workflows for that Jira ticket and asks the user to choose when more than one exists.
  - `review <WORKFLOW_DIR> [CUSTOM_FEEDBACK]` reviews the latest implementation iteration for that workflow.
  - `review <ITERATION_DIR> [CUSTOM_FEEDBACK]` reviews that exact iteration.
  - `<JIRA_KEY> review [CUSTOM_FEEDBACK]`, `<WORKFLOW_DIR> review [CUSTOM_FEEDBACK]`, and `<ITERATION_DIR> review [CUSTOM_FEEDBACK]` are equivalent ticket-first forms.
  - `CUSTOM_FEEDBACK` is free-form quoted text from the user, for example `$one-shot-this AGC-126 review "Custom review feedback that should be addressed"`.
- Environment variables (if set):
  - `WORKSPACE_ROOT`: folder that contains local clones of repos (default: current directory)
  - `BASE_BRANCH`: default base branch for worktrees (default: main)

## Paper trail layout
- Create paper-trail artifacts in the directory where the skill is invoked.
- Use this hierarchy:
  - `<JIRA_KEY>/`
  - `<JIRA_KEY>/workflow-<UUID>/`
  - `<JIRA_KEY>/workflow-<UUID>/iteration-###/`
- A Jira ticket can have many workflow folders. Each workflow is an independent implementation attempt.
- A workflow can have many iterations. Iterations represent the loop `implement -> review -> implement -> review` until the code is good.
- Worktrees are workflow-scoped and reused across iterations so fixes build on prior implementation work.

## Artifact contract
- `<JIRA_KEY>/ticket_manifest.json`: Jira-level index of workflow attempts.
- `<JIRA_KEY>/workflow-<UUID>/workflow_manifest.json`: workflow ID, Jira key, base branch, repo list, stable worktree paths, branches, current iteration, and tmux session history.
- `<JIRA_KEY>/workflow-<UUID>/plan.json`: approved implementation plan.
- `iteration-###/iteration_manifest.json`: iteration number, packet paths, prior review links, review output path, and session metadata.
- `iteration-###/packets/implement/`: one implementation packet per repo.
- `iteration-###/packets/review.md`: one consolidated review packet for all affected repos.
- `iteration-###/reviews/user_feedback.md`: optional custom review feedback provided by the user.
- `iteration-###/reviews/review.md`: consolidated review findings.
- `iteration-###/reviews/next_implement_plan.json`: revised plan produced by review when another implementation iteration is needed.
- `iteration-###/summaries/implementation.md`: implementation worker summaries and test results.

## Implement mode: new workflow
Use for `implement <JIRA_KEY>`.

### Step 1 — Requirements intake (read-only)
1) Use Jira MCP to fetch:
   - title, description, acceptance criteria, links, attachments
2) Summarize requirements and list assumptions/questions.

### Step 2 — Repo selection using service catalog (read-only)
1) Use service-catalog MCP to find impacted repos/services.
2) Produce a list of repos with:
   - why impacted
   - key modules/files likely touched
   - integration/dependency notes

### Step 3 — Plan
Output a structured plan with:
- `jira_key`
- `issue_type` and/or title when known, so branch type can be inferred
- `repos`: list of `{ name, local_path (if known), branch_suffix, branch_type (optional), steps[], tests[], rollout_notes }`
- `cross_repo_steps` (if any)
Then ask for approval:
`Approve to generate workflow paper trail + implementation workers?`

STOP if not approved.

### Step 4 — Generate workflow, packets, and workers
1) Run `scripts/init_workflow.py <JIRA_KEY>` to create `<JIRA_KEY>/workflow-<UUID>/iteration-001/`.
2) Save the approved plan JSON as an input file.
3) Run `scripts/write_work_packets.py <plan.json> <workflow_dir> <workflow_dir>/iteration-001`.
4) Run `scripts/spawn_tmux_worktrees.sh <workflow_dir> <workflow_dir>/iteration-001`.
5) After spawn succeeds, do not run extra tmux verification commands.
6) Final response for this step must be a single instruction line:
   - `tmux attach -t codex-<JIRA_KEY>-<shortUUID>-i001`

## Implement mode: next iteration
Use for `implement <WORKFLOW_DIR>` after review findings exist.

1) Read `<WORKFLOW_DIR>/workflow_manifest.json`.
2) Read all prior `iteration-###/reviews/review.md` files.
3) Run `scripts/next_iteration.py <WORKFLOW_DIR>` to create the next iteration.
4) Reuse `<WORKFLOW_DIR>/plan.json` as the plan input unless the user explicitly approved a revised plan.
5) Run `scripts/write_work_packets.py <plan.json> <workflow_dir> <new_iteration_dir>`.
6) Run `scripts/spawn_tmux_worktrees.sh <workflow_dir> <new_iteration_dir>`.
7) Final response for this step must be a single instruction line:
   - `tmux attach -t codex-<JIRA_KEY>-<shortUUID>-i###`

## Review mode
Use one review process for all affected repos. Review reads the previous implementation iteration, optional user feedback, service descriptions, and coding best practices. If changes are needed, review produces a revised implement plan and asks inside the review tmux session whether to spawn the next implementation iteration.

1) Resolve the target:
   - If given a Jira key, find `<JIRA_KEY>/workflow-*` under the invocation directory.
   - If more than one workflow exists, list them with current iteration and ask the user to choose.
   - If given a workflow directory, review its latest iteration.
   - If given an iteration directory, review that exact iteration.
2) If custom feedback was provided, pass it to the packet writer with `--feedback <CUSTOM_FEEDBACK>`.
3) Run `scripts/write_review_packet.py <workflow_dir> [iteration_dir] [--feedback <CUSTOM_FEEDBACK>]`.
   - For ticket-first syntax, normalize to the same target + feedback before running this script.
   - If feedback is long or multiline, write it to a temporary file and use `--feedback-file <path>`.
4) Run `scripts/spawn_review_tmux.sh <workflow_dir> [iteration_dir]`.
5) After spawn succeeds, do not run extra tmux verification commands.
6) Final response for this step must be a single instruction line:
   - `tmux attach -t codex-review-<JIRA_KEY>-<shortUUID>-i###`

## Implementation worker rules
- Operate only within the assigned repo/worktree.
- Implement per packet.
- Treat prior review findings as required context and do not repeat the same mistakes.
- Run tests listed in the packet.
- Branch naming defaults to `feature/<branch_suffix>`. Use `bugfix/<branch_suffix>` only when the story explicitly indicates a bug fix or the plan sets `branch_type: bugfix`.
- Append a concise summary, tests run, results, and risks to `iteration-###/summaries/implementation.md`.
- Before any push or PR, explicitly ask:
  `Approve push + PR for <repo>?`
- If approved:
  - ensure the current local branch tracks `origin/<current-branch>` (do not only check that some upstream exists)
  - if tracking is missing or points elsewhere (for example `origin/main`), set/fix it by pushing with upstream tracking (for example `git push -u origin <branch>`)
  - create PR (prefer gh; otherwise print the exact manual command)
- Report back with:
  - branch name
  - PR link
  - tests run + results
  - any follow-ups/risks

## Review worker rules
- Review all affected repos in one Codex process.
- Inspect each repo's implementation diff against the workflow base branch.
- Read each target repo's `service_description.md` when present and verify nothing violates the service responsibilities or integrations.
- Validate changes against Jira requirements, the approved plan, implementation packets, prior review findings, and optional custom user feedback.
- Check coding best practices, maintainability, error handling, integration risks, and cross-repo consistency.
- Verify unit, integration, and e2e test coverage is adequate for the changed behavior.
- Run relevant tests when practical; otherwise document exactly what should be run and why it was not run.
- Do not push or create PRs.
- Write consolidated findings to `iteration-###/reviews/review.md`, including:
  - Decision: `approved` or `needs-changes`
  - Blocking findings
  - Non-blocking findings
  - Test coverage assessment
  - Cross-repo consistency risks
  - Do-not-repeat guidance for the next implementation iteration
- If the decision is `needs-changes`, write a complete revised implementation plan JSON to `iteration-###/reviews/next_implement_plan.json`.
- The revised plan must use the same schema as the approved plan consumed by `scripts/write_work_packets.py`.
- After writing the revised plan, ask exactly:
  `Approve revised implement plan and spawn next implementation iteration?`
- If approved, run:
  - `scripts/next_iteration.py <workflow_dir>`
  - `scripts/write_work_packets.py <iteration-###/reviews/next_implement_plan.json> <workflow_dir> <new_iteration_dir>`
  - `scripts/spawn_tmux_worktrees.sh <workflow_dir> <new_iteration_dir>`
- If the decision is `approved`, do not create a next implementation iteration.

## Existing path handling
- Workflow creation must retry UUID generation if a workflow directory already exists.
- Iteration creation must choose the next available `iteration-###` and fail clearly if that exact directory already exists unexpectedly.
- Worktree creation must gracefully reuse an existing compatible worktree on the expected branch.
- If the expected worktree path exists but is not a compatible git worktree, fail with a clear message instead of a raw `already exists` error.
- If a tmux session already exists, fail clearly and print the existing session name.

## Gradle worktree reliability (Nebula/Grgit)
- Only for repos that use Gradle, run Gradle tests in spawned worktrees via `./.codex-gradle-test.sh`.
- The launcher only copies this wrapper when the worktree contains `./gradlew`.
- The launcher uses `${SHELL}` when present instead of assuming Bash.
- Gradle worktrees should use the user's normal Gradle configuration from `~/.gradle` by default.
- A workspace-local Gradle configuration may override the default when the launched workspace intentionally provides one.
- This wrapper exists to make Gradle run safely from git worktrees and always passes `-Pgit.root=<repo-root>` to avoid `nebula.release`/`grgit` failures like `.../config (Is a directory)`.
- If a Gradle-based packet lists `./gradlew test --tests ...`, execute the same arguments via `./.codex-gradle-test.sh` instead.
