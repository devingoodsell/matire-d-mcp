#!/usr/bin/env bash
# Run tests with coverage reporting.
# Fails if coverage drops below 100%.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "--- Running tests with coverage ---"
python -m pytest \
    --cov=src \
    --cov-branch \
    --cov-report=term-missing \
    --cov-fail-under=100 \
    --tb=short \
    "$@"
