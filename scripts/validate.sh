#!/usr/bin/env bash
# Full validation pipeline: lint + typecheck + test + coverage
# Run this after completing any story or task.
# Exit code is non-zero if ANY step fails.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "========================================"
echo "  Restaurant MCP — Full Validation"
echo "========================================"
echo ""

# Step 1: Lint
echo "--- [1/3] Linting (ruff) ---"
python -m ruff check src/ tests/
echo "Lint: PASSED"
echo ""

# Step 2: Tests + Coverage
echo "--- [2/3] Tests + Coverage ---"
python -m pytest \
    --cov=src \
    --cov-branch \
    --cov-report=term-missing \
    --cov-fail-under=100 \
    --tb=short \
    -q
echo "Tests + Coverage: PASSED"
echo ""

# Step 3: Import check (no circular imports)
echo "--- [3/3] Import check ---"
python -c "import src" 2>&1
echo "Import check: PASSED"
echo ""

echo "========================================"
echo "  ALL CHECKS PASSED"
echo "========================================"
