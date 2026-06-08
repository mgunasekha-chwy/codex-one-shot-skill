#!/usr/bin/env python3
import argparse
import shutil
import sys
from pathlib import Path

from paper_trail import (
    branch_name,
    load_iteration,
    load_workflow,
    previous_review_texts,
    repo_file_name,
    resolve_local_path,
    save_iteration,
    save_workflow,
    utc_now,
    worktree_path,
    read_json,
    write_json,
)


TEMPLATE = """# Implementation Packet: {repo}

## Paper Trail
- Jira: {jira_key}
- Workflow: {workflow_dir}
- Iteration: {iteration}
- Iteration directory: {iteration_dir}
- Workflow manifest: {workflow_manifest}
- Iteration manifest: {iteration_manifest}
- Plan: {plan_path}
- Implementation summary to update: {implementation_summary}

## Repo Context
- Repo: {repo}
- Local clone: {local_path}
- Worktree: {worktree_path}
- Branch: {branch}
- Base branch: {base_branch}

## Objective
Implement the approved plan for this repo only.

## Steps
{steps}

## Tests to run
{tests}

## Prior Review Findings
{prior_reviews}

## Build tool note
{build_tool_note}

## Push and PR note
- When the user gives final approval to push and open a PR, ensure the current local branch tracks `origin/<current-branch>`.
- Do not only check whether an upstream exists; it may exist but point to `origin/main` or `origin/master`.
- A safe generic sequence is:
  - `branch="$(git branch --show-current)"`
  - `upstream="$(git for-each-ref --format='%(upstream:short)' "refs/heads/$branch")"`
  - `if [[ "$upstream" != "origin/$branch" ]]; then git push -u origin "$branch"; fi`

## Constraints
- Only change this repo/worktree.
- Keep commits small and logical.
- Do not push or create a PR without asking for approval in this session.
- If prior review findings exist, fix them directly and do not repeat the same mistakes.
- Append a concise implementation result, tests run, and risks to the implementation summary file.

## Definition of done
- Tests pass or failures are clearly explained in the implementation summary
- Prior blocking review findings for this repo are addressed
- PR opened only after explicit approval
- Summary posted back with branch, PR link if any, test results, and follow-ups
"""


def bullet(lines):
    if not lines:
        return "- (none)"
    return "\n".join([f"- {x}" for x in lines])


def build_tool_note(repo_config):
    if repo_config.get("build_tool") == "gradle":
        return "- This repo is marked as Gradle-based. In worktrees, run Gradle commands via `./.codex-gradle-test.sh` with the same args."
    return "- If this repo has a `./gradlew` wrapper in the spawned worktree, use `./.codex-gradle-test.sh` for Gradle commands. Otherwise use the repo's native test/build command."


def format_prior_reviews(iteration_manifest):
    reviews = previous_review_texts(iteration_manifest)
    if not reviews:
        return "- No prior review findings for this workflow."
    sections = []
    for path, text in reviews:
        sections.append(f"### {path}\n\n{text.strip() or '(empty review file)'}")
    return "\n\n".join(sections)


def upsert_repo(existing_repos, repo_update):
    for idx, repo in enumerate(existing_repos):
        if repo.get("name") == repo_update["name"]:
            merged = dict(repo)
            merged.update(repo_update)
            existing_repos[idx] = merged
            return
    existing_repos.append(repo_update)


def main():
    parser = argparse.ArgumentParser(
        description="Write per-repo implementation packets for one workflow iteration."
    )
    parser.add_argument("plan_json", help="Approved implementation plan JSON")
    parser.add_argument("workflow_dir", help="Path to workflow-<UUID>")
    parser.add_argument("iteration_dir", help="Path to iteration-###")
    parser.add_argument(
        "--workspace-root",
        default=None,
        help="Folder containing local repo clones. Defaults to WORKSPACE_ROOT or cwd.",
    )
    args = parser.parse_args()

    try:
        plan_path = Path(args.plan_json).resolve()
        workflow_path, workflow_manifest = load_workflow(args.workflow_dir)
        iteration_path, iteration_manifest = load_iteration(args.iteration_dir)
        plan = read_json(plan_path)
    except Exception as exc:
        print(f"Failed to load packet inputs: {exc}", file=sys.stderr)
        return 2

    jira_key = plan.get("jira_key") or plan.get("issue") or workflow_manifest.get("jira_key")
    if jira_key != workflow_manifest.get("jira_key"):
        print(
            f"Plan Jira key {jira_key} does not match workflow Jira key {workflow_manifest.get('jira_key')}",
            file=sys.stderr,
        )
        return 2

    repos = plan.get("repos", [])
    if not repos:
        print("Plan JSON has no repos[]", file=sys.stderr)
        return 2

    workflow_plan_path = workflow_path / "plan.json"
    if plan_path != workflow_plan_path:
        shutil.copyfile(plan_path, workflow_plan_path)
    else:
        write_json(workflow_plan_path, plan)

    workspace_root = args.workspace_root or workflow_manifest.get("workspace_root") or workflow_manifest.get("invocation_cwd")
    packets_dir = iteration_path / "packets" / "implement"
    packets_dir.mkdir(parents=True, exist_ok=True)
    prior_reviews = format_prior_reviews(iteration_manifest)
    implementation_summary = iteration_manifest["implementation_summary"]

    packet_paths = []
    workflow_repos = workflow_manifest.setdefault("repos", [])
    for repo_config in repos:
        repo = repo_config["name"]
        local_path = resolve_local_path(repo_config, workspace_root)
        branch = branch_name(plan, jira_key, repo_config)
        wt_path = worktree_path(local_path, jira_key, workflow_manifest["workflow_id"])
        packet_path = packets_dir / f"{repo_file_name(repo)}.md"

        content = TEMPLATE.format(
            jira_key=jira_key,
            workflow_dir=workflow_path,
            iteration=iteration_manifest["iteration"],
            iteration_dir=iteration_path,
            workflow_manifest=workflow_path / "workflow_manifest.json",
            iteration_manifest=iteration_path / "iteration_manifest.json",
            plan_path=workflow_plan_path,
            implementation_summary=implementation_summary,
            repo=repo,
            local_path=local_path,
            worktree_path=wt_path,
            branch=branch,
            base_branch=workflow_manifest.get("base_branch", "main"),
            steps=bullet(repo_config.get("steps", [])),
            tests=bullet(repo_config.get("tests", [])),
            prior_reviews=prior_reviews,
            build_tool_note=build_tool_note(repo_config),
        )
        packet_path.write_text(content)
        packet_paths.append(str(packet_path))

        upsert_repo(
            workflow_repos,
            {
                "name": repo,
                "local_path": local_path,
                "worktree_path": wt_path,
                "branch": branch,
                "implementation_packet": str(packet_path),
                "tests": repo_config.get("tests", []),
                "build_tool": repo_config.get("build_tool"),
            },
        )

    iteration_manifest["implementation_packets"] = packet_paths
    iteration_manifest["updated_at"] = utc_now()
    workflow_manifest["workspace_root"] = str(Path(workspace_root).resolve())
    workflow_manifest["updated_at"] = utc_now()
    save_iteration(iteration_path, iteration_manifest)
    save_workflow(workflow_path, workflow_manifest)
    print(packets_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
