# The bench in the cloud sandbox

How `scripts/dev/bench_up.sh` behaves in the agents' cloud sandbox. Every number below was
measured on 2026-11-10 by task M0-T1 (Frappe 15.126.0, branch `version-15`). The first facts
(HTTP blocked, root, MariaDB absent) come from the operator's smoke test the same day and were
confirmed, not rediscovered.

## Commands

```bash
cd /workspace/attention_center
# A cold run takes 3 to 10 minutes, longer than a tool call may last: run it detached and poll.
nohup bash scripts/dev/bench_up.sh > /tmp/bench_up.out 2>&1 &
tail -n 3 /tmp/bench_up.out          # repeat until the last line says "ready" or "failed"
bash scripts/ci/run_tests.sh         # everything CI runs
```

- Progress lines carry the elapsed seconds (`== [ 147s] creating site test_site`). The verbose
  output of apt, pip and bench goes to `/tmp/bench_up.log` (`BENCH_UP_LOG`); its last 40 lines
  are printed when a step fails.
- Re-running on a ready bench takes 3–4 s and can run in the foreground. It re-runs
  `install-app` (a no-op when installed), `set-config allow_tests` and `migrate`.
- Overrides: `BENCH_DIR` (`~/frappe-bench`), `FRAPPE_BRANCH` (`version-15`), `SITE`
  (`test_site`), `DB_ROOT_PASSWORD` (`root`), `BENCH_UP_LOG`. The site's Administrator
  password is `admin`. These are throwaway local values.
- Interrupted runs: a site whose creation was interrupted (directory present, Frappe not
  installed) is recreated with `new-site --force` (measured: 20 s). An interrupted `bench init`
  is detected (`sites/apps.txt` lacks `frappe`) and the script stops with a message instead of
  deleting a directory it cannot prove it owns; run `rm -rf ~/frappe-bench` and start again.

## Environment observed

| Item | Value |
|---|---|
| User | `root` (uid 0) |
| OS | Ubuntu 24.04.5 LTS, kernel 6.18, 4 vCPU |
| Memory | 16 086 MB, no swap |
| Disk | 30 GB free on `/` at session start (11.1 GB used) |
| Python | 3.11.17 (`/usr/local/bin/python3`); `uv` present, `bench init` uses it |
| Node | 22.22.0, yarn 1.22.22, npm 10.9.4 |
| Pre-installed services | Redis (not running), PostgreSQL 16 (unused). MariaDB absent |
| Browser tooling | Python Playwright 1.56.0, Chromium 1194 in `/opt/pw-browsers` (`PLAYWRIGHT_BROWSERS_PATH`) |
| Network | HTTPS egress works (GitHub, PyPI, npm registry, Ubuntu mirrors); plain HTTP is blocked. One 16 MB wheel from PyPI downloaded in 5.0 s |

## Measured durations from a cold sandbox

Run 1 was the first command of a fresh session (script as on `main`, timed by a wrapper).
Run 2 used the final script in the same sandbox after removing MariaDB (packages, data,
`/etc/mysql`), the apt lists and cache, the Redis processes, the bench CLI, `~/frappe-bench`
and the uv, yarn and pip caches, and after restoring the `http://` apt sources. Only the bench
CLI's own dependencies stayed installed.

| Step | Run 1 | Run 2 |
|---|---|---|
| Install MariaDB 10.11 from Ubuntu over HTTPS (`apt-get update` + `install`) | 225 s (of which dpkg 11 s) | 60 s |
| Start MariaDB, set root password and utf8mb4 | 1 s | 1 s |
| Install the bench CLI (`pip install frappe-bench`) | 7 s | 2 s |
| `bench init --frappe-branch version-15` | 297 s: venv 2 s, shallow clone 1 s, `uv pip install` of Frappe 279 s, `yarn install` 15 s | 81 s |
| Link the repository, `pip install -e` | 8 s | 3 s |
| `bench new-site test_site` | 19 s | 19 s |
| `install-app`, `set-config allow_tests`, `migrate` | 4 s | 4 s |
| `bench build --app frappe` | not in that script; 12 s when run alone | 11 s |
| **Total** | **561 s (9 min 21 s)** + 12 s build | **181 s (3 min 1 s)** |

Downloads dominate and their speed varies between runs (the operator's run took about 4 minutes;
run 2 used 67 s user and 30 s system CPU over 181 s). Other measurements:

| Action | Duration |
|---|---|
| `bash scripts/ci/run_tests.sh` (38 coordinator tests, 1 backend test) | 1.0 s |
| `bench_up.sh` on a ready bench | 3–4 s |
| `bench --site test_site serve --port 8000` until `/login` answers | 2.1 s |
| `bench build --app frappe` on its own | 10–12 s |

## Disk and memory

- Disk: 11 191 MB used before run 2, 13 697 MB after it (+2.5 GB). `~/frappe-bench` 1.2 GB
  (`env` 702 MB, `apps/frappe` 495 MB including 320 MB of `node_modules`), MariaDB data
  224 MB, yarn cache 603 MB, uv cache 213 MB (it held 1.1 GB at one point during run 1's
  install).
- Memory used (`free -m`): 662 MB with MariaDB and both Redis servers idle after setup
  (`mariadbd` 150 MB RSS); 961 MB with `bench serve` running after two Chromium visits; peak
  1 974 MB during `bench build --app frappe`.

## Problems and fixes

| Problem | Fix |
|---|---|
| Plain-HTTP egress is blocked; the sandbox's apt sources use `http://` mirrors | `bench_up.sh` rewrites `archive`/`security.ubuntu.com` to `https://` before `apt-get update` |
| `bench init` exits when run as root unless the config in its working directory names a `frappe_user` | `bench_up.sh` runs init from a scratch directory holding `{"frappe_user": "root"}`; the new bench records the user |
| `/usr/sbin/policy-rc.d` exits 101, so apt does not start MariaDB after installing it | `bench_up.sh` starts it with `service mariadb start` (works without systemd), falling back to `mysqld_safe` |
| `bench new-site` warns that MariaDB 10.11 is newer than 10.8 and untested | Harmless: the site installs and the tests pass. CI uses MariaDB 10.6 |
| `bench init --skip-assets` leaves Frappe unbuilt; `/login` then answers HTTP 500 (`AttributeError: 'NoneType' object has no attribute 'get'` in `bundled_asset`) | `bench_up.sh` runs `bench build --app frappe` when `sites/assets/frappe/dist` is missing |
| The output is large (the `new-site` progress bar alone is one 30 KB line) | Tool output goes to `/tmp/bench_up.log`; the terminal gets one line per step |
| A cold run outlasts a 5-minute tool call, and an interrupted run left a half-made bench or site that the old existence checks skipped | Run detached (see Commands); the script now checks completeness, not existence |

PostgreSQL fallback: not needed. MariaDB installs and starts in the sandbox, so local runs and CI
both use MariaDB (10.11 locally, 10.6 in CI) and the pre-installed PostgreSQL stays unused.

## Browser check (Playwright)

Chromium can load the desk login page from the sandbox bench. With `bench --site test_site
serve --port 8000` running, headless Chromium (Python Playwright) got HTTP 200 for
`http://127.0.0.1:8000/login`, title "Login", the e-mail field and login button visible, three
stylesheets and no failed request; launch plus load took 0.87–0.95 s over four visits. Logging
in as Administrator reached the desk in 1.15–1.33 s with no page errors. A fresh site sends the desk to
`/app/setup-wizard/0`, so UI work (screenshots, the M6 smoke suite) must complete the setup
wizard first; `bench_up.sh` does not. Before Frappe's assets were built the same visit got
HTTP 500.

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
	browser = p.chromium.launch()
	page = browser.new_page()
	response = page.goto("http://127.0.0.1:8000/login", wait_until="networkidle")
	assert response.status == 200 and page.locator("#login_email").is_visible()
	page.screenshot(path="/tmp/login.png")
	browser.close()
```

## CI compared with the sandbox

| | CI (`.github/workflows/ci.yml`) | Sandbox |
|---|---|---|
| Setup script | `scripts/ci/install.sh` | `scripts/dev/bench_up.sh` |
| MariaDB | 10.6 service container | 10.11 from Ubuntu, local |
| Redis | two service containers on 13000 and 11000 | two local `redis-server` on the same ports |
| Python / Node | 3.11 (setup-python) / 18 | 3.11.17 / 22.22.0 |
| Tests | `scripts/ci/run_tests.sh` | the same script |
