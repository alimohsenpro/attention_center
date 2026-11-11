#!/usr/bin/env bash
# Single test entry point. CI runs it, and agents run it in the sandbox before submitting.
# Add new test suites here, never in the workflow.
set -euo pipefail

: "${BENCH_DIR:=$HOME/frappe-bench}"
: "${SITE:=test_site}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "== pipeline coordinator tests"
python3 -m unittest "$REPO_DIR/scripts/pipeline/test_status.py"

echo "== client unit tests"
# Files, not the directory: Node 18 (CI) and Node 22 (sandbox) read a directory argument differently.
node --test "$REPO_DIR"/tests/js/*.test.js

echo "== backend tests"
cd "$BENCH_DIR"
bench --site "$SITE" run-tests --app attention_center

echo "== UI smoke tests (skipped when Playwright for Python or its Chromium is missing)"
BENCH_DIR="$BENCH_DIR" SITE="$SITE" python3 "$REPO_DIR/tests/ui/test_smoke.py"
