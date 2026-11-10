#!/usr/bin/env bash
# Bring up a Frappe 15 bench with this repository installed as a live (symlinked) app.
# Intended for the cloud sandbox and for any Ubuntu machine. Safe to re-run.
#
# Verified in the cloud sandbox by an operator smoke test on 2026-11-10 (about 4 minutes from
# a fresh sandbox). Task M0-T1 records the details in docs/SANDBOX.md.
set -euo pipefail

: "${BENCH_DIR:=$HOME/frappe-bench}"
: "${FRAPPE_BRANCH:=version-15}"
: "${SITE:=test_site}"
: "${DB_ROOT_PASSWORD:=root}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

log() { printf '\n== %s\n' "$*"; }
SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

db_ping() { mariadb-admin ping --silent >/dev/null 2>&1 || mariadb-admin -uroot -p"$DB_ROOT_PASSWORD" ping --silent >/dev/null 2>&1; }

start_mariadb() {
  if db_ping; then return 0; fi
  if ! command -v mariadbd >/dev/null 2>&1 && ! command -v mysqld >/dev/null 2>&1; then
    log "installing MariaDB"
    # Some sandboxes block plain-HTTP egress; the Ubuntu mirrors also serve HTTPS.
    $SUDO sed -i -E 's#http://(archive|security)\.ubuntu\.com#https://\1.ubuntu.com#g' \
      /etc/apt/sources.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq mariadb-server mariadb-client libmariadb-dev pkg-config
  fi
  log "starting MariaDB"
  $SUDO service mariadb start >/dev/null 2>&1 || ($SUDO mysqld_safe --user=mysql >/tmp/mariadb.log 2>&1 &)
  for _ in $(seq 1 60); do db_ping && break; sleep 1; done
  db_ping || { echo "MariaDB did not start; see /tmp/mariadb.log"; return 1; }
  $SUDO mariadb -e "ALTER USER 'root'@'localhost' IDENTIFIED BY '$DB_ROOT_PASSWORD'; FLUSH PRIVILEGES;" 2>/dev/null || true
  mariadb -uroot -p"$DB_ROOT_PASSWORD" -e "SET GLOBAL character_set_server='utf8mb4'; SET GLOBAL collation_server='utf8mb4_unicode_ci';"
}

start_redis() {
  for port in 13000 11000; do
    redis-cli -p "$port" ping >/dev/null 2>&1 || redis-server --port "$port" --daemonize yes --save "" --appendonly no >/dev/null
  done
}

install_bench() {
  if ! command -v bench >/dev/null 2>&1; then
    log "installing bench"
    pip install --quiet frappe-bench || pip install --quiet --break-system-packages frappe-bench
  fi
  if [ ! -d "$BENCH_DIR/apps/frappe" ]; then
    log "bench init ($FRAPPE_BRANCH)"
    # bench exits as root unless the config in the working directory names a frappe_user.
    # A created bench records the invoking user, so only init needs this scratch config.
    local init_cwd; init_cwd="$(mktemp -d)"
    mkdir -p "$init_cwd/sites"
    printf '{"frappe_user": "%s"}\n' "$(id -un)" > "$init_cwd/sites/common_site_config.json"
    (cd "$init_cwd" && bench init --skip-redis-config-generation --skip-assets --no-backups \
      --frappe-branch "$FRAPPE_BRANCH" "$BENCH_DIR")
    rm -rf "$init_cwd"
  fi
}

install_app() {
  cd "$BENCH_DIR"
  if [ ! -e apps/attention_center ]; then
    log "linking the repository into the bench"
    ln -s "$REPO_DIR" apps/attention_center
    ./env/bin/pip install --quiet -e apps/attention_center
  fi
  grep -qx "attention_center" sites/apps.txt || printf '\nattention_center\n' >> sites/apps.txt
  if [ ! -d "sites/$SITE" ]; then
    log "creating site $SITE"
    bench new-site --db-root-password "$DB_ROOT_PASSWORD" --admin-password admin "$SITE"
  fi
  bench --site "$SITE" list-apps | grep -q "attention_center" || bench --site "$SITE" install-app attention_center
  bench --site "$SITE" set-config allow_tests true
  bench --site "$SITE" migrate >/dev/null
  if [ -n "$(find "$REPO_DIR/attention_center/public" -name '*.bundle.*' -print -quit 2>/dev/null)" ]; then
    bench build --app attention_center
  fi
}

start_mariadb
start_redis
install_bench
install_app
log "ready: cd $BENCH_DIR && bench --site $SITE run-tests --app attention_center"
