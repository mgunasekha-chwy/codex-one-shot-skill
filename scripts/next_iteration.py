#!/usr/bin/env python3
import argparse
import sys

from paper_trail import create_next_iteration


def main():
    parser = argparse.ArgumentParser(
        description="Create the next implement/review iteration for a workflow."
    )
    parser.add_argument("workflow_dir", help="Path to workflow-<UUID>")
    args = parser.parse_args()

    try:
        iteration_path = create_next_iteration(args.workflow_dir)
    except Exception as exc:
        print(f"Failed to create next iteration: {exc}", file=sys.stderr)
        return 2

    print(iteration_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
