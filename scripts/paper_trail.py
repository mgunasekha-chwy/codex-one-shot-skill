#!/usr/bin/env python3
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def repo_file_name(repo_name):
    return repo_name.replace("/", "-")


def ticket_dir(root, jira_key):
    return Path(root) / jira_key


def workflow_dir(root, jira_key, workflow_id):
    return ticket_dir(root, jira_key) / f"workflow-{workflow_id}"


def iteration_name(number):
    return f"iteration-{number:03d}"


def iteration_dir(workflow_path, number):
    return Path(workflow_path) / iteration_name(number)


def validate_jira_key(jira_key):
    if not re.match(r"^[A-Z][A-Z0-9]+-\d+$", jira_key):
        raise ValueError(f"Invalid Jira key: {jira_key}")


def infer_branch_prefix(plan, repo_config):
    explicit_value = repo_config.get("branch_type") or plan.get("branch_type")
    if explicit_value:
        normalized = str(explicit_value).strip().lower()
        if normalized in {"bugfix", "bug", "fix", "hotfix"}:
            return "bugfix"
        if normalized in {"feature", "feat"}:
            return "feature"

    explicit_text = " ".join(
        str(value)
        for value in (
            repo_config.get("story_type"),
            plan.get("story_type"),
            repo_config.get("issue_type"),
            plan.get("issue_type"),
            plan.get("title"),
            plan.get("summary"),
        )
        if value
    ).lower()
    if re.search(r"\b(bug|bugfix|fix|defect|hotfix|regression)\b", explicit_text):
        return "bugfix"
    return "feature"


def branch_name(plan, jira_key, repo_config):
    explicit_branch = repo_config.get("branch")
    if explicit_branch:
        return explicit_branch

    suffix = repo_config.get("branch_suffix") or f"{jira_key}-{repo_config['name']}".replace("/", "-")
    suffix = str(suffix).strip().lstrip("/")
    return f"{infer_branch_prefix(plan, repo_config)}/{suffix}"


def resolve_local_path(repo_config, workspace_root):
    local_path = repo_config.get("local_path")
    if local_path:
        return str(Path(local_path).expanduser().resolve())
    return str((Path(workspace_root) / repo_config["name"].split("/")[-1]).resolve())


def worktree_path(local_path, jira_key, workflow_id):
    local = Path(local_path)
    short_id = workflow_id.split("-", 1)[0]
    return str(local.parent / f"{local.name}-{jira_key}-{short_id}")


def load_workflow(workflow_path):
    workflow_path = Path(workflow_path).resolve()
    manifest_path = workflow_path / "workflow_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Workflow manifest not found: {manifest_path}")
    return workflow_path, read_json(manifest_path)


def save_workflow(workflow_path, manifest):
    write_json(Path(workflow_path) / "workflow_manifest.json", manifest)


def load_iteration(iteration_path):
    iteration_path = Path(iteration_path).resolve()
    manifest_path = iteration_path / "iteration_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Iteration manifest not found: {manifest_path}")
    return iteration_path, read_json(manifest_path)


def save_iteration(iteration_path, manifest):
    write_json(Path(iteration_path) / "iteration_manifest.json", manifest)


def latest_iteration(workflow_path):
    workflow_path = Path(workflow_path)
    candidates = []
    for child in workflow_path.iterdir():
        match = re.fullmatch(r"iteration-(\d{3})", child.name)
        if child.is_dir() and match:
            candidates.append((int(match.group(1)), child))
    if not candidates:
        raise FileNotFoundError(f"No iteration directories found in {workflow_path}")
    return max(candidates)[1]


def next_iteration_number(workflow_path):
    workflow_path = Path(workflow_path)
    highest = 0
    if workflow_path.exists():
        for child in workflow_path.iterdir():
            match = re.fullmatch(r"iteration-(\d{3})", child.name)
            if child.is_dir() and match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def create_workflow(root, jira_key, base_branch="main"):
    validate_jira_key(jira_key)
    root = Path(root).resolve()
    ticket_path = ticket_dir(root, jira_key)
    ticket_path.mkdir(parents=True, exist_ok=True)
    ticket_manifest_path = ticket_path / "ticket_manifest.json"

    if ticket_manifest_path.exists():
        ticket_manifest = read_json(ticket_manifest_path)
    else:
        ticket_manifest = {
            "jira_key": jira_key,
            "created_at": utc_now(),
            "workflows": [],
        }

    for _ in range(10):
        workflow_id = str(uuid.uuid4())
        workflow_path = workflow_dir(root, jira_key, workflow_id)
        try:
            workflow_path.mkdir(parents=False, exist_ok=False)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError(f"Could not create unique workflow directory for {jira_key}")

    iteration_path = iteration_dir(workflow_path, 1)
    (iteration_path / "packets" / "implement").mkdir(parents=True, exist_ok=False)
    (iteration_path / "packets").mkdir(exist_ok=True)
    (iteration_path / "reviews").mkdir(exist_ok=True)
    (iteration_path / "summaries").mkdir(exist_ok=True)

    workflow_manifest = {
        "jira_key": jira_key,
        "workflow_id": workflow_id,
        "workflow_dir": str(workflow_path),
        "ticket_dir": str(ticket_path),
        "invocation_cwd": str(root),
        "base_branch": base_branch,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "current_iteration": 1,
        "repos": [],
        "sessions": [],
        "iterations": [str(iteration_path)],
    }
    iteration_manifest = {
        "jira_key": jira_key,
        "workflow_id": workflow_id,
        "iteration": 1,
        "iteration_dir": str(iteration_path),
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "previous_reviews": [],
        "implementation_packets": [],
        "review_packet": None,
        "review_output": str(iteration_path / "reviews" / "review.md"),
        "implementation_summary": str(iteration_path / "summaries" / "implementation.md"),
    }

    save_workflow(workflow_path, workflow_manifest)
    save_iteration(iteration_path, iteration_manifest)

    ticket_manifest.setdefault("workflows", []).append(
        {
            "workflow_id": workflow_id,
            "workflow_dir": str(workflow_path),
            "created_at": workflow_manifest["created_at"],
            "current_iteration": 1,
        }
    )
    ticket_manifest["updated_at"] = utc_now()
    write_json(ticket_manifest_path, ticket_manifest)
    return workflow_path


def create_next_iteration(workflow_path):
    workflow_path, workflow_manifest = load_workflow(workflow_path)
    number = next_iteration_number(workflow_path)
    iteration_path = iteration_dir(workflow_path, number)
    iteration_path.mkdir(parents=False, exist_ok=False)
    (iteration_path / "packets" / "implement").mkdir(parents=True, exist_ok=False)
    (iteration_path / "reviews").mkdir(exist_ok=True)
    (iteration_path / "summaries").mkdir(exist_ok=True)

    previous_reviews = []
    for prior in sorted(workflow_path.glob("iteration-[0-9][0-9][0-9]/reviews/review.md")):
        previous_reviews.append(str(prior.resolve()))

    manifest = {
        "jira_key": workflow_manifest["jira_key"],
        "workflow_id": workflow_manifest["workflow_id"],
        "iteration": number,
        "iteration_dir": str(iteration_path),
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "previous_reviews": previous_reviews,
        "implementation_packets": [],
        "review_packet": None,
        "review_output": str(iteration_path / "reviews" / "review.md"),
        "implementation_summary": str(iteration_path / "summaries" / "implementation.md"),
    }
    save_iteration(iteration_path, manifest)

    workflow_manifest["current_iteration"] = number
    workflow_manifest.setdefault("iterations", []).append(str(iteration_path))
    workflow_manifest["updated_at"] = utc_now()
    save_workflow(workflow_path, workflow_manifest)
    return iteration_path


def previous_review_texts(iteration_manifest):
    texts = []
    for review_path in iteration_manifest.get("previous_reviews", []):
        path = Path(review_path)
        if path.is_file():
            texts.append((str(path), path.read_text()))
    return texts
