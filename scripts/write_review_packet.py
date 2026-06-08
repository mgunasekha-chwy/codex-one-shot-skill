#!/usr/bin/env python3
import argparse
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

## Review Objective
Review all affected repos for this workflow iteration in one process. Determine whether the implementation is good enough to ship or needs another implement/review iteration.

## Affected Repos
{repos}

## Prior Review Findings
{prior_reviews}

## Required Review Procedure
- Inspect each repo's implementation diff against the workflow base branch.
- Read each repo's `service_description.md` when present and verify the changes fit the service responsibilities and integrations.
- Validate behavior against the Jira requirements, approved plan, implementation packets, and prior review findings.
- Check coding best practices, maintainability, error handling, integration risks, and cross-repo consistency.
- Verify unit, integration, and e2e test coverage is adequate for the changed behavior.
- Run relevant tests where practical. If tests cannot be run, explain exactly why and what should be run.
- Do not push branches or create PRs.
- Write consolidated findings to `{review_output}`.

## Output Format
Write `{review_output}` with these sections:
- Decision: `approved` or `needs-changes`
- Blocking findings
- Non-blocking findings
- Test coverage assessment
- Cross-repo consistency risks
- Do-not-repeat guidance for the next implementation iteration
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
    args = parser.parse_args()

    try:
        workflow_path, workflow_manifest = load_workflow(args.workflow_dir)
        iteration_path = Path(args.iteration_dir).resolve() if args.iteration_dir else latest_iteration(workflow_path)
        iteration_path, iteration_manifest = load_iteration(iteration_path)
        plan_path = workflow_path / "plan.json"
        if not plan_path.is_file():
            raise FileNotFoundError(f"Plan file not found: {plan_path}")
        read_json(plan_path)
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

    content = TEMPLATE.format(
        jira_key=workflow_manifest["jira_key"],
        workflow_dir=workflow_path,
        iteration=iteration_manifest["iteration"],
        iteration_dir=iteration_path,
        workflow_manifest=workflow_path / "workflow_manifest.json",
        iteration_manifest=iteration_path / "iteration_manifest.json",
        plan_path=plan_path,
        review_output=review_output,
        repos="\n\n".join(format_repo(repo) for repo in repos),
        prior_reviews=format_prior_reviews(iteration_manifest),
    )
    review_packet.write_text(content)

    iteration_manifest["review_packet"] = str(review_packet)
    iteration_manifest["review_output"] = str(review_output)
    iteration_manifest["updated_at"] = utc_now()
    save_iteration(iteration_path, iteration_manifest)
    print(review_packet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
