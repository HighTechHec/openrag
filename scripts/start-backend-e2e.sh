#!/bin/bash
set -e

# Go to project root
cd "$(dirname "$0")/.."

# Run Setup (Factory Reset + Infra Start)
# We assume setup-e2e.sh is in scripts/
./scripts/setup-e2e.sh

# Now start the backend
echo "Starting Backend..."
uv run python src/main.py
