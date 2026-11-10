#!/usr/bin/env bash
# Single test entry point. CI runs it, and agents run it in the sandbox before submitting.
# Add new test suites here (for example the JS unit tests in task M3-T1), never in the workflow.
set -euo pipefail

: "${BENCH_DIR:=$HOME/frappe-bench}"
: "${SITE:=test_site}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "== pipeline coordinator tests"
python3 -m unittest "$REPO_DIR/scripts/pipeline/test_status.py"

echo "== backend tests"
cd "$BENCH_DIR"
bench --site "$SITE" run-tests --app attention_center
