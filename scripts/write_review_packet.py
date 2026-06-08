#!/usr/bin/env python3
import argparse
import shlex
import sys
from pathlib import Path

from paper_trail import (
    latest_iteration,
    load_iteration,
    load_workflow,
    previous_review_texts,
    read_json,
    save_iteration,
    utc_now,
)


TEMPLATE = """# Consolidated Review Packet

## Paper Trail
- Jira: {jira_key}
- Workflow: {workflow_dir}
- Iteration: {iteration}
- Iteration directory: {iteration_dir}
- Workflow manifest: {workflow_manifest}
- Iteration manifest: {iteration_manifest}
- Plan: {plan_path}
- Review output: {review_output}
- User feedback: {user_feedback_path}
- Next implement plan: {next_implement_plan}

## Review Objective
Review all affected repos for this workflow iteration in one process. Determine whether the implementation is good enough to ship or needs another implement/review iteration. If changes are needed, produce a revised implementation plan and ask the user whether to spawn the next implementation iteration from this review session.

## Affected Repos
{repos}

## User Review Feedback
{user_feedback}

## Prior Review Findings
{prior_reviews}

## Required Review Procedure
- Inspect each repo's implementation diff against the workflow base branch.
- Use the previous implementation iteration's changes as the review target; do not review unrelated local changes outside the recorded worktrees.
- Read each repo's `service_description.md` when present and verify the changes fit the service responsibilities and integrations.
- Validate behavior against the Jira requirements, approved plan, implementation packets, prior review findings, and user review feedback.
- Check coding best practices, maintainability, error handling, integration risks, and cross-repo consistency.
- Verify unit, integration, and e2e test coverage is adequate for the changed behavior.
- Run relevant tests where practical. If tests cannot be run, explain exactly why and what should be run.
- Do not push branches or create PRs.
- Write consolidated findings to `{review_output}`.
- If the decision is `needs-changes`, write a complete revised implementation plan JSON to `{next_implement_plan}` using the same schema consumed by `write_work_packets.py`.
- After writing a `needs-changes` plan, ask exactly: `Approve revised implement plan and spawn next implementation iteration?`
- If the user approves, run the handoff commands below from this review session.
- If the decision is `approved`, do not create a next implementation iteration.

## Output Format
Write `{review_output}` with these sections:
- Decision: `approved` or `needs-changes`
- Blocking findings
- Non-blocking findings
- Test coverage assessment
- Cross-repo consistency risks
- Do-not-repeat guidance for the next implementation iteration

## Revised Plan Requirements
When changes are needed, `{next_implement_plan}` must be valid JSON with:
- `jira_key`: `{jira_key}`
- `issue_type` and/or `title` when known
- `repos`: complete list of repo objects to implement next, each with `name`, `local_path`, `branch_suffix`, optional `branch_type`, `steps`, `tests`, and `rollout_notes`
- `cross_repo_steps` when relevant

Start from `{plan_path}`, keep unaffected repo metadata intact, and change only the steps/tests/notes needed to address this review.

## Approved Handoff Commands
Only after the user approves the revised plan, run:

```bash
new_iteration="$({next_iteration_script} {workflow_dir_arg})"
{write_work_packets_script} {next_implement_plan_arg} {workflow_dir_arg} "$new_iteration"
{spawn_implement_script} {workflow_dir_arg} "$new_iteration"
```

Then tell the user to attach to the printed implementation tmux session.
"""


def format_repo(repo):
    return "\n".join(
        [
            f"### {repo['name']}",
            f"- Local clone: {repo.get('local_path')}",
            f"- Worktree: {repo.get('worktree_path')}",
            f"- Branch: {repo.get('branch')}",
            f"- Implementation packet: {repo.get('implementation_packet')}",
            f"- Tests from plan: {repo.get('tests') or []}",
        ]
    )


def format_prior_reviews(iteration_manifest):
    reviews = previous_review_texts(iteration_manifest)
    if not reviews:
        return "- No prior review findings for this workflow."
    sections = []
    for path, text in reviews:
        sections.append(f"### {path}\n\n{text.strip() or '(empty review file)'}")
    return "\n\n".join(sections)


def read_feedback(args):
    parts = []
    if args.feedback:
        parts.append(args.feedback)
    if args.feedback_file:
        feedback_file = Path(args.feedback_file).expanduser().resolve()
        if not feedback_file.is_file():
            raise FileNotFoundError(f"Feedback file not found: {feedback_file}")
        parts.append(feedback_file.read_text())
    return "\n\n".join(part.strip() for part in parts if part.strip())


def format_user_feedback(feedback):
    if not feedback:
        return "- No custom user review feedback provided."
    return feedback.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Write one consolidated review packet for a workflow iteration."
    )
    parser.add_argument("workflow_dir", help="Path to workflow-<UUID>")
    parser.add_argument(
        "iteration_dir",
        nargs="?",
        help="Path to iteration-###. Defaults to the workflow's latest iteration.",
    )
    parser.add_argument(
        "--feedback",
        default=None,
        help="Custom user review feedback to include in the review packet.",
    )
    parser.add_argument(
        "--feedback-file",
        default=None,
        help="Path to a file containing custom user review feedback.",
    )
    args = parser.parse_args()

    try:
        workflow_path, workflow_manifest = load_workflow(args.workflow_dir)
        iteration_path = Path(args.iteration_dir).resolve() if args.iteration_dir else latest_iteration(workflow_path)
        iteration_path, iteration_manifest = load_iteration(iteration_path)
        plan_path = workflow_path / "plan.json"
        if not plan_path.is_file():
            raise FileNotFoundError(f"Plan file not found: {plan_path}")
        read_json(plan_path)
        feedback = read_feedback(args)
    except Exception as exc:
        print(f"Failed to load review inputs: {exc}", file=sys.stderr)
        return 2

    repos = workflow_manifest.get("repos", [])
    if not repos:
        print("Workflow manifest has no repos[]; write implementation packets first", file=sys.stderr)
        return 2

    packets_dir = iteration_path / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    review_packet = packets_dir / "review.md"
    review_output = iteration_path / "reviews" / "review.md"
    review_output.parent.mkdir(parents=True, exist_ok=True)
    user_feedback_path = review_output.parent / "user_feedback.md"
    if feedback:
        user_feedback_path.write_text(feedback.strip() + "\n")
        user_feedback_manifest_value = str(user_feedback_path)
    else:
        user_feedback_manifest_value = None
    next_implement_plan = review_output.parent / "next_implement_plan.json"
    script_dir = Path(__file__).resolve().parent

    content = TEMPLATE.format(
        jira_key=workflow_manifest["jira_key"],
        workflow_dir=workflow_path,
        iteration=iteration_manifest["iteration"],
        iteration_dir=iteration_path,
        workflow_manifest=workflow_path / "workflow_manifest.json",
        iteration_manifest=iteration_path / "iteration_manifest.json",
        plan_path=plan_path,
        review_output=review_output,
        user_feedback_path=user_feedback_manifest_value or "(none)",
        next_implement_plan=next_implement_plan,
        repos="\n\n".join(format_repo(repo) for repo in repos),
        user_feedback=format_user_feedback(feedback),
        prior_reviews=format_prior_reviews(iteration_manifest),
        next_iteration_script=shlex.quote(str(script_dir / "next_iteration.py")),
        write_work_packets_script=shlex.quote(str(script_dir / "write_work_packets.py")),
        spawn_implement_script=shlex.quote(str(script_dir / "spawn_tmux_worktrees.sh")),
        workflow_dir_arg=shlex.quote(str(workflow_path)),
        next_implement_plan_arg=shlex.quote(str(next_implement_plan)),
    )
    review_packet.write_text(content)

    iteration_manifest["review_packet"] = str(review_packet)
    iteration_manifest["user_feedback"] = user_feedback_manifest_value
    iteration_manifest["review_output"] = str(review_output)
    iteration_manifest["next_implement_plan"] = str(next_implement_plan)
    iteration_manifest["updated_at"] = utc_now()
    save_iteration(iteration_path, iteration_manifest)
    print(review_packet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
