#!/usr/bin/env python3
"""Read-only environment diagnosis, except for disposable write probes."""
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

MODULES = ("numpy", "scipy", "pandas", "sklearn", "matplotlib", "cv2")
REPO_ROOT = Path(__file__).resolve().parents[1]


def data_paths(repo_root, environment):
    """Resolve relative overrides against the repository, never the caller cwd."""
    root = Path(environment.get("RPPG_DATA_ROOT", "data")).expanduser()
    if not root.is_absolute():
        root = repo_root / root
    return {"raw": root / "raw", "processed": root / "processed", "runs": repo_root / "runs"}


def check_gpu():
    command = shutil.which("nvidia-smi")
    if command is None:
        return {"status": "unavailable", "required_for_cpu": False}
    try:
        result = subprocess.run(
            [command, "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return {"status": "available", "required_for_cpu": False, "details": result.stdout.strip()}
    except (OSError, subprocess.SubprocessError) as error:
        return {"status": "error", "required_for_cpu": False, "error": str(error)}


def diagnose(repo_root=REPO_ROOT, environment=None):
    if environment is None:
        environment = os.environ
    python = {"version": sys.version, "ok": sys.version_info[:2] == (3, 11)}
    imports = {}
    for name in MODULES:
        try:
            importlib.import_module(name)
            imports[name] = {"ok": True}
        except Exception as error:
            imports[name] = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    paths = {}
    for name, path in data_paths(repo_root, environment).items():
        try:
            if not path.is_dir():
                raise NotADirectoryError(f"Directory missing or invalid: {path}")
            with tempfile.TemporaryFile(dir=path) as probe:
                probe.write(b"rppg write probe")
                probe.flush()
            paths[name] = {"path": str(path), "ok": True}
        except OSError as error:
            paths[name] = {"path": str(path), "ok": False, "error": str(error)}
    return {
        "cpu_ready": python["ok"] and all(item["ok"] for item in imports.values())
        and all(item["ok"] for item in paths.values()),
        "python": python, "imports": imports, "paths": paths, "gpu": check_gpu(),
    }


def main():
    report = diagnose()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["cpu_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
