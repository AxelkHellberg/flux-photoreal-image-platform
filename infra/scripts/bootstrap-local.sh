#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

uv sync --all-packages
pnpm install

echo "Local bootstrap completed. Review .env before starting the stack."
