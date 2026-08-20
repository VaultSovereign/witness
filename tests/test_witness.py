"""Regression tests for the portable Witness Receipt CLI."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = [sys.executable, str(ROOT / "witness.py")]


class WitnessCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(CLI + list(args), text=True, capture_output=True, cwd=ROOT)

    def create_verified(self, folder: Path, evidence: Path) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "create", "--out", str(folder), "--objective", "Merge a PR",
            "--scope", "repository PR #1", "--success", "PR is merged",
            "--principal", "operator", "--actor", "agent",
            "--boundary", "repository write permission", "--operation", "Read checks",
            "--evidence", str(evidence), "--claim", "PR merged",
            "--status", "VERIFIED", "--verify-mechanism", "Post-mutation API re-read",
        )

    def test_create_and_verify_verified_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = root / "response.json"
            evidence.write_text('{"merged": true}\n', encoding="utf-8")
            receipt = root / "receipt"
            created = self.create_verified(receipt, evidence)
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertTrue((receipt / "receipt.json").is_file())
            self.assertTrue((receipt / "receipt.md").is_file())
            self.assertEqual(self.run_cli("verify", str(receipt)).returncode, 0)

    def test_verified_requires_a_named_mechanism_and_leaves_no_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "invalid"
            result = self.run_cli(
                "create", "--out", str(folder), "--objective", "x", "--scope", "y",
                "--success", "z", "--principal", "p", "--actor", "a", "--boundary", "b",
                "--claim", "c", "--status", "VERIFIED",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("verification_mechanism", result.stderr)
            self.assertFalse(folder.exists())

    def test_duplicate_evidence_names_are_retained_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            one, two = root / "one", root / "two"
            one.mkdir()
            two.mkdir()
            first, second = one / "same.txt", two / "same.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            receipt = root / "receipt"
            result = self.run_cli(
                "create", "--out", str(receipt), "--objective", "x", "--scope", "y",
                "--success", "z", "--principal", "p", "--actor", "a", "--boundary", "b",
                "--claim", "c", "--evidence", str(first), "--evidence", str(second),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.run_cli("verify", str(receipt)).returncode, 0)
            items = json.loads((receipt / "receipt.json").read_text())["evidence"]["items"]
            self.assertNotEqual(items[0]["retained_as"], items[1]["retained_as"])

    def test_verify_detects_tampered_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = root / "evidence.txt"
            evidence.write_text("original", encoding="utf-8")
            receipt = root / "receipt"
            self.assertEqual(self.create_verified(receipt, evidence).returncode, 0)
            next((receipt / "evidence").iterdir()).write_text("modified", encoding="utf-8")
            result = self.run_cli("verify", str(receipt))
            self.assertEqual(result.returncode, 1)
            self.assertIn("digest mismatch", result.stdout)

    def test_verify_rejects_evidence_path_outside_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = root / "receipt"
            receipt.mkdir()
            outside = root / "outside.txt"
            outside.write_text("private", encoding="utf-8")
            digest = __import__("hashlib").sha256(outside.read_bytes()).hexdigest()
            malicious = {
                "request": {}, "authority": {}, "action": {"operations": []},
                "evidence": {"items": [{"retained_as": "../outside.txt", "digest": f"sha256:{digest}"}]},
                "result": {"status": "RECORDED"},
            }
            (receipt / "receipt.json").write_text(json.dumps(malicious), encoding="utf-8")
            result = self.run_cli("verify", str(receipt))
            self.assertEqual(result.returncode, 1)
            self.assertIn("escapes receipt package", result.stdout)

    def test_verify_handles_malformed_receipt_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipt = Path(temp) / "receipt"
            receipt.mkdir()
            (receipt / "receipt.json").write_text('{"evidence":{"items":"not-a-list"}}', encoding="utf-8")
            result = self.run_cli("verify", str(receipt))
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()