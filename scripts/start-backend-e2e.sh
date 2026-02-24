#!/bin/bash
set -e

# Go to project root
cd "$(dirname "$0")/.."

# Environment file for E2E tests
E2E_ENV="frontend/.env.test"

# Run Setup (Factory Reset + Infra Start)
# We assume setup-e2e.sh is in scripts/
./scripts/setup-e2e.sh

# Now start the backend
echo "Starting Backend using $E2E_ENV..."
make backend ENV_FILE=$E2E_ENV
