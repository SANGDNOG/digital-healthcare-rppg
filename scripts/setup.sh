#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
if [[ -x "$REPO_ROOT/.tools/bin/uv" ]]; then
    UV="$REPO_ROOT/.tools/bin/uv"
elif command -v uv >/dev/null 2>&1; then
    UV="$(command -v uv)"
else
    echo 'uv is required. Install uv or provision .tools/bin/uv, then rerun bash scripts/setup.sh.' >&2
    exit 1
fi
"$UV" sync --locked --python 3.11
# Python handles tilde expansion and repository-relative overrides consistently with doctor.
"$UV" run --locked python - <<'PY'
import os
from pathlib import Path
from scripts.doctor import data_paths
for path in data_paths(Path.cwd(), os.environ).values():
    path.mkdir(parents=True, exist_ok=True)
PY
"$UV" run --locked python scripts/doctor.py
