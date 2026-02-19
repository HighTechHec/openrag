#!/bin/bash
set -e

# Go to project root
cd "$(dirname "$0")/.."

# Backup .env if it exists and is not a symlink to .env.test
if [ -f .env ] && [ ! -f .env.bak ]; then
    echo "Backing up .env to .env.bak"
    cp .env .env.bak
fi

# Overwrite .env with .env.test
echo "Overwriting .env with frontend/.env.test"
cp frontend/.env.test .env

# Detect container runtime
if command -v docker >/dev/null 2>&1; then
    CONTAINER_RUNTIME="docker"
else
    CONTAINER_RUNTIME="podman"
fi

echo "Using container runtime: $CONTAINER_RUNTIME"
echo "Starting E2E Setup..."

# Clean up using make
echo "Cleaning up..."
make factory-reset FORCE=true

# Start infrastructure using make (this will use the new .env)
echo "Starting infrastructure..."
make dev-local-cpu

echo "Waiting for OpenSearch..."
until curl -s -k https://localhost:9200 >/dev/null; do
    sleep 5
    echo "Waiting for OpenSearch..."
done

echo "Waiting for Langflow..."
until curl -s http://localhost:7860/health >/dev/null; do
    sleep 5
    echo "Waiting for Langflow..."
done

echo "Infrastructure Ready!"
