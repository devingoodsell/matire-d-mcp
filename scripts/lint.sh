#!/usr/bin/env bash
# Quick lint check using ruff.
# Use --fix to auto-fix issues: ./scripts/lint.sh --fix

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

if [[ "${1:-}" == "--fix" ]]; then
    echo "--- Linting with auto-fix ---"
    python -m ruff check --fix src/ tests/
    python -m ruff format src/ tests/
else
    echo "--- Linting (check only) ---"
    python -m ruff check src/ tests/
    echo ""
    echo "Tip: Run './scripts/lint.sh --fix' to auto-fix issues."
fi
