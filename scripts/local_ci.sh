#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

python_bin="${YXMEEGLE_PYTHON:-}"
if [[ -z "$python_bin" ]]; then
  if [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
  elif command -v python3.12 >/dev/null 2>&1; then
    python_bin="$(command -v python3.12)"
  else
    printf 'Python 3.12 is required. Create .venv with Python 3.12 and install backend/requirements.lock.\n' >&2
    exit 1
  fi
fi

python_version="$("$python_bin" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$python_version" != "3.12" ]]; then
  printf 'Expected Python 3.12, got %s (%s). Set YXMEEGLE_PYTHON to a Python 3.12 executable.\n' "$python_version" "$python_bin" >&2
  exit 1
fi
if ! "$python_bin" -c 'import pytest' >/dev/null 2>&1; then
  printf 'Backend test dependencies are missing. Install with: %s -m pip install --require-hashes -r backend/requirements.lock\n' "$python_bin" >&2
  exit 1
fi

node_major="$(node -p 'Number(process.versions.node.split(".")[0])' 2>/dev/null || true)"
if [[ -z "$node_major" || "$node_major" -lt 22 ]]; then
  printf 'Node.js 22 or newer is required to run frontend checks.\n' >&2
  exit 1
fi

printf '\n== Backend tests (Python %s) ==\n' "$python_version"
"$python_bin" -m pytest backend -q

printf '\n== Frontend install and checks (Node %s) ==\n' "$(node --version)"
cd "$repo_root/frontend"
npm ci
npm run test:session-epoch
npm run test:api-response
node test-company-route.mjs
npm run build
npm run test:dev-tooling

printf '\nLocal pre-push checks passed.\n'
