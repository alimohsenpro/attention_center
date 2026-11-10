#!/usr/bin/env bash
# CI only: build a bench against the service containers declared in .github/workflows/ci.yml.
set -euo pipefail

: "${BENCH_DIR:=$HOME/frappe-bench}"
: "${FRAPPE_BRANCH:=version-15}"
: "${SITE:=test_site}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

sudo apt-get update -qq
sudo apt-get install -y -qq mariadb-client

pip install --quiet frappe-bench
bench init --skip-redis-config-generation --skip-assets --python "$(which python)" \
  --frappe-branch "$FRAPPE_BRANCH" "$BENCH_DIR"

mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "SET GLOBAL character_set_server = 'utf8mb4'"
mariadb --host 127.0.0.1 --port 3306 -u root -proot -e "SET GLOBAL collation_server = 'utf8mb4_unicode_ci'"

cd "$BENCH_DIR"
bench get-app attention_center "$REPO_DIR"
bench setup requirements --dev
bench new-site --db-root-password root --admin-password admin "$SITE"
bench --site "$SITE" install-app attention_center
bench build --app attention_center
bench --site "$SITE" set-config allow_tests true
