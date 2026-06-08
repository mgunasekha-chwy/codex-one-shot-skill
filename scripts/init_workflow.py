#!/usr/bin/env python3
import argparse
import os
import sys

from paper_trail import create_workflow


def main():
    parser = argparse.ArgumentParser(
        description="Create a Jira ticket workflow paper trail and first iteration."
    )
    parser.add_argument("jira_key", help="Jira issue key, for example AGC-124")
    parser.add_argument(
        "--base-branch",
        default=os.environ.get("BASE_BRANCH", "main"),
        help="Base branch for workflow worktrees. Defaults to BASE_BRANCH or main.",
    )
    parser.add_argument(
        "--root",
        default=os.getcwd(),
        help="Directory where the Jira ticket folder should be created.",
    )
    args = parser.parse_args()

    try:
        workflow_path = create_workflow(args.root, args.jira_key, args.base_branch)
    except Exception as exc:
        print(f"Failed to initialize workflow: {exc}", file=sys.stderr)
        return 2

    print(workflow_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
