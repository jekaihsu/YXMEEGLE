#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

existing="$(git config --local --get core.hooksPath || true)"
if [[ -n "$existing" && "$existing" != ".githooks" ]]; then
  printf 'Not changing existing local core.hooksPath: %s\n' "$existing" >&2
  exit 1
fi
global_existing="$(git config --global --get core.hooksPath || true)"
if [[ -n "$global_existing" && "$global_existing" != ".githooks" ]]; then
  printf 'Not overriding existing global core.hooksPath: %s\n' "$global_existing" >&2
  exit 1
fi

git config --local core.hooksPath .githooks
printf 'Enabled repository-local Git hooks at .githooks\n'
