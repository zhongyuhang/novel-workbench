#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== backend =="
cd "${ROOT}/backend"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -e ".[dev]"
alembic upgrade head
ruff check .
ruff format --check .
mypy app
pytest -q

echo "== frontend =="
cd "${ROOT}/frontend"
npm ci
npm run build
npm run lint
