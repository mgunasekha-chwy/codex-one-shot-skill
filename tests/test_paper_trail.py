import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from paper_trail import create_next_iteration, create_workflow, read_json


class PaperTrailTest(unittest.TestCase):
    def test_create_workflow_creates_ticket_workflow_and_first_iteration(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow = create_workflow(tmp, "AGC-124", "main")

            self.assertEqual(workflow.parent.name, "AGC-124")
            self.assertRegex(workflow.name, r"^workflow-[0-9a-f-]{36}$")
            self.assertTrue((workflow / "iteration-001").is_dir())
            self.assertTrue((workflow / "iteration-001" / "packets" / "implement").is_dir())

            ticket_manifest = read_json(Path(tmp) / "AGC-124" / "ticket_manifest.json")
            workflow_manifest = read_json(workflow / "workflow_manifest.json")
            iteration_manifest = read_json(workflow / "iteration-001" / "iteration_manifest.json")

            self.assertEqual(ticket_manifest["jira_key"], "AGC-124")
            self.assertEqual(workflow_manifest["current_iteration"], 1)
            self.assertEqual(iteration_manifest["iteration"], 1)

    def test_create_workflow_retries_uuid_collision(self):
        first = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        second = uuid.UUID("660e8400-e29b-41d4-a716-446655440000")
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "AGC-124" / f"workflow-{first}"
            existing.mkdir(parents=True)

            with patch("paper_trail.uuid.uuid4", side_effect=[first, second]):
                workflow = create_workflow(tmp, "AGC-124", "main")

            self.assertEqual(workflow.name, f"workflow-{second}")

    def test_next_iteration_links_prior_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow = create_workflow(tmp, "AGC-124", "main")
            review = workflow / "iteration-001" / "reviews" / "review.md"
            review.write_text("needs changes")

            iteration = create_next_iteration(workflow)
            manifest = read_json(iteration / "iteration_manifest.json")

            self.assertEqual(iteration.name, "iteration-002")
            self.assertEqual(manifest["previous_reviews"], [str(review.resolve())])

    def test_write_work_and_review_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            workflow = create_workflow(tmp, "AGC-124", "main")
            iteration = workflow / "iteration-001"
            local_repo = tmp_path / "service-a"
            local_repo.mkdir()
            plan = {
                "jira_key": "AGC-124",
                "title": "Add thing",
                "repos": [
                    {
                        "name": "service-a",
                        "local_path": str(local_repo),
                        "branch_suffix": "AGC-124-service-a",
                        "steps": ["Change API"],
                        "tests": ["pytest"],
                    }
                ],
            }
            plan_path = tmp_path / "plan.json"
            plan_path.write_text(json.dumps(plan))

            env = os.environ.copy()
            env["PYTHONPATH"] = str(SCRIPTS_DIR)
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "write_work_packets.py"),
                    str(plan_path),
                    str(workflow),
                    str(iteration),
                ],
                check=True,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
            )

            workflow_manifest = read_json(workflow / "workflow_manifest.json")
            iteration_manifest = read_json(iteration / "iteration_manifest.json")
            packet = iteration / "packets" / "implement" / "service-a.md"

            self.assertTrue(packet.is_file())
            self.assertIn("AGC-124", packet.read_text())
            self.assertEqual(len(workflow_manifest["repos"]), 1)
            self.assertEqual(iteration_manifest["implementation_packets"], [str(packet)])
            self.assertIn("service-a-AGC-124-", workflow_manifest["repos"][0]["worktree_path"])

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "write_review_packet.py"),
                    str(workflow),
                    str(iteration),
                ],
                check=True,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
            )

            review_packet = iteration / "packets" / "review.md"
            iteration_manifest = read_json(iteration / "iteration_manifest.json")
            self.assertTrue(review_packet.is_file())
            self.assertEqual(iteration_manifest["review_packet"], str(review_packet))
            self.assertIn("Consolidated Review Packet", review_packet.read_text())


if __name__ == "__main__":
    unittest.main()
