"""Exercise doctor output and failure propagation without requiring GPU hardware."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
DOCTOR = REPO / "scripts" / "doctor.py"


class DoctorCLI(unittest.TestCase):
    def test_import_failure_returns_nonzero_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "raw").mkdir()
            (root / "processed").mkdir()
            (root / "scipy.py").write_text("raise ImportError('broken scipy fixture')\n")
            result = subprocess.run(
                [sys.executable, str(DOCTOR)], cwd=temporary,
                env={**os.environ, "RPPG_DATA_ROOT": str(root), "PYTHONPATH": str(root)},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertFalse(report["cpu_ready"])
            self.assertIn("broken scipy fixture", report["imports"]["scipy"]["error"])

    def test_missing_paths_fail_with_json_without_creating_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "missing data"
            result = subprocess.run(
                [sys.executable, str(DOCTOR)], cwd=temporary,
                env={**os.environ, "RPPG_DATA_ROOT": str(root)},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertFalse(report["cpu_ready"])
            self.assertFalse(root.exists())


class DoctorChecks(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("doctor", DOCTOR)
        self.doctor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.doctor)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        for relative in ("data/raw", "data/processed", "runs"):
            (self.repo / relative).mkdir(parents=True)

    def check(self, environment=None):
        with patch.object(self.doctor.importlib, "import_module", return_value=object()), \
             patch.object(self.doctor.sys, "version_info", (3, 11, 9)), \
             patch.object(self.doctor.shutil, "which", return_value=None):
            return self.doctor.diagnose(self.repo, environment or {})

    def test_default_paths_are_repo_relative_and_gpu_is_optional(self):
        report = self.check()
        self.assertTrue(report["cpu_ready"])
        self.assertEqual(report["paths"]["raw"]["path"], str(self.repo / "data/raw"))
        self.assertEqual(report["gpu"]["status"], "unavailable")
        self.assertEqual(list((self.repo / "data/raw").iterdir()), [])

    def test_override_with_spaces_preserves_existing_data(self):
        root = Path(self.temporary.name) / "external data"
        (root / "raw").mkdir(parents=True)
        (root / "processed").mkdir()
        original = root / "raw" / "original.txt"
        original.write_text("preserve me")
        report = self.check({"RPPG_DATA_ROOT": str(root)})
        self.assertTrue(report["cpu_ready"])
        self.assertEqual(report["paths"]["raw"]["path"], str(root / "raw"))
        self.assertEqual(original.read_text(), "preserve me")
        self.assertEqual(sorted(p.name for p in (root / "raw").iterdir()), ["original.txt"])

    def test_file_as_data_root_fails(self):
        root = Path(self.temporary.name) / "file"
        root.write_text("not a directory")
        self.assertFalse(self.check({"RPPG_DATA_ROOT": str(root)})["cpu_ready"])

    def test_relative_override_uses_repository(self):
        (self.repo / "relative data/raw").mkdir(parents=True)
        (self.repo / "relative data/processed").mkdir()
        report = self.check({"RPPG_DATA_ROOT": "relative data"})
        self.assertTrue(report["cpu_ready"])
        self.assertEqual(report["paths"]["raw"]["path"], str(self.repo / "relative data/raw"))

    def test_import_failure_is_reported(self):
        real_import = self.doctor.importlib.import_module

        def import_module(name):
            if name == "scipy":
                raise ImportError("broken scipy fixture")
            return real_import(name)

        with patch.object(self.doctor.importlib, "import_module", side_effect=import_module):
            report = self.doctor.diagnose(self.repo, {})
        self.assertFalse(report["cpu_ready"])
        self.assertIn("broken scipy fixture", report["imports"]["scipy"]["error"])

    def test_write_failure_fails_cpu_readiness(self):
        with patch.object(self.doctor.tempfile, "TemporaryFile", side_effect=PermissionError("read only")):
            report = self.check()
        self.assertFalse(report["cpu_ready"])
        self.assertIn("read only", report["paths"]["raw"]["error"])

    def test_wrong_python_fails(self):
        with patch.object(self.doctor.sys, "version_info", (3, 12, 1)):
            report = self.doctor.diagnose(self.repo, {})
        self.assertFalse(report["python"]["ok"])
        self.assertFalse(report["cpu_ready"])

    def test_gpu_command_failure_is_advisory(self):
        with patch.object(self.doctor.shutil, "which", return_value="/fixture/nvidia-smi"), \
             patch.object(self.doctor.subprocess, "run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 5)):
            gpu = self.doctor.check_gpu()
        self.assertEqual(gpu["status"], "error")


if __name__ == "__main__":
    unittest.main()
