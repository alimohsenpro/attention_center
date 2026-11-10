# Attention Center — Delivery Plan

Ordered tasks for the build pipeline (`pipeline/README.md`). One task = one branch
`task/<ID>` = one pull request. Tasks are done strictly in the order of `pipeline/tasks.json`;
a task starts only when every task it depends on is merged.

Requirement IDs refer to `docs/PRD.md`; section numbers (§) refer to `docs/TECH_DESIGN.md`.

## Definition of done (every task)

1. The task's acceptance criteria below are met, and nothing outside its scope changed.
2. New behaviour has tests that fail without the change. Permission-sensitive code has a negative test (a user who must *not* see something).
3. `bash scripts/ci/run_tests.sh` passes locally in the sandbox bench before the PR is submitted.
4. Every new user-visible string is wrapped for translation and added to `attention_center/translations/ar.csv` in simple, familiar Arabic.
5. No organisation-specific names, hosts, data or credentials anywhere in the repository.
6. Documentation touched by the change is updated in the same PR (`docs/TECH_DESIGN.md` when the design changed; `docs/DECISIONS.md` when a decision was taken).
7. The PR description lists: what changed, requirement IDs covered, how it was tested, and anything deferred.
8. CI is green and the reviewer agent approved. Merging is done by the pipeline, never by the builder.

## Milestones

| Milestone | Goal | Release |
|---|---|---|
| M0 | The pipeline can build and test the app in the sandbox and in CI | — |
| M1 | Data model, source engine, built-in sources, server API | 0.1 |
| M2 | Realtime nudges | 0.1 |
| M3 | Client core: launcher, window, modes, refresh loop | 0.1 |
| M4 | Alert policy, sound, login and reminders | 0.1 |
| M5 | Settings and governance UI | 0.1 |
| M6 | Hardening, translation, docs, release 0.1.0 | 0.1 |
| M7 | Announcements, snooze, extra sources, health → release 0.2.0 | 0.2 |

Cost guide (list prices, builder on Sonnet 5.5 unless the operator overrides): a typical task is
USD 2–4 for the builder plus about USD 1 per review. Budgets per run are enforced by the
deployments (`pipeline/README.md`).

---

## Tasks

### M0-T1 — Sandbox bench and green CI

- Requirements: NFR-MAINT-01
- Depends on: —
- Scope: `scripts/dev/bench_up.sh`, `scripts/ci/*.sh`, `docs/SANDBOX.md`, one trivial backend test, `attention_center/tests/`.
- Already known from the operator's smoke test on 2026-11-10 (record it in `docs/SANDBOX.md`, re-measure the timings, do not rediscover it): the sandbox runs as root on Ubuntu 24.04 with Python 3.11, Node 22, yarn and Redis present and MariaDB absent; plain-HTTP egress is blocked while HTTPS works, so the environment has no package pre-install and `bench_up.sh` switches the apt mirrors to HTTPS; `bench init` refuses to run as root without a `frappe_user` config; with both handled, `bench_up.sh` takes about 4 minutes from a fresh sandbox and `scripts/ci/run_tests.sh` passes; MariaDB 10.11 triggers a version warning from `bench new-site` but works. CI on `main` is green.
- Do:
  1. Make `scripts/dev/bench_up.sh` bring up a working Frappe 15 bench in the cloud sandbox: start MariaDB and Redis, `bench init --frappe-branch version-15`, create site `test_site`, install this app from the mounted repository, enable tests. The script must be idempotent and safe to re-run.
  2. If MariaDB cannot be installed or started in the sandbox, fall back to the pre-installed PostgreSQL for local runs only (`bench new-site --db-type postgres`), keep MariaDB in CI, and record the limitation in `docs/SANDBOX.md`.
  3. Make `scripts/ci/run_tests.sh` the single test entry point (backend tests; JS tests are added in M3-T1) and make the CI workflow pass on your PR. You cannot change files under `.github/workflows/`; if one must change, escalate.
  4. Add one meaningful backend test (for example: the app is installed and its module is registered).
  5. Write `docs/SANDBOX.md`: exact commands, measured durations of each step, disk and memory observed, problems and fixes, and whether Playwright's Chromium can load the desk login page from the sandbox bench (`bench serve` + headless visit).
- Acceptance: a fresh sandbox reaches a passing `bash scripts/ci/run_tests.sh` by running only `bash scripts/dev/bench_up.sh`; CI is green; `docs/SANDBOX.md` contains measured numbers, not estimates.

### M1-T1 — DocTypes, role and install hooks

- Requirements: FR-SET-01, FR-SET-02, FR-SET-03, FR-SRC-01 (AC1), FR-SRC-02 (AC3), FR-SRC-03 (AC2)
- Depends on: M0-T1
- Scope: §3.1–§3.3; `install.py`; `hooks.py` (after_install, after_migrate, fixtures for the role); DocType controllers and their tests.
- Do: create `Attention Center Settings`, `Attention Source` (+ `Attention Source Role`, `Attention Source User Group`), `Attention User Preference` exactly as in §3; controller validation as specified; role `Attention Manager` created on install; a workspace is *not* part of this task.
- Acceptance: tests cover every validation rule (accept and reject cases), including "Python source cannot be created from the desk" and "system sources reject definition edits"; settings bounds are enforced; DocTypes install and migrate cleanly on a fresh site.

### M1-T2 — Source contract and registry

- Requirements: FR-SRC-01, FR-SRC-03, FR-SRC-06, FR-PERM-04
- Depends on: M1-T1
- Scope: `engine/contract.py`, `engine/registry.py`, sync in `install.py`; tests.
- Do: §4.1–§4.3 and §4.6: definition validation, item normalisation, hook loading, sync into `Attention Source` preserving admin-owned fields, `get_visible_sources(user)` with targeting by role and User Group and DocType read permission, per-user visibility cache with invalidation.
- Acceptance: tests with fake hook entries (patch `frappe.get_hooks`) cover: valid declarative and python definitions, each rejection reason, duplicate keys, unsupported `contract_version`, sync idempotency, admin changes preserved across sync, vanished hook source disabled; visibility tests with two users, roles and a User Group, including the negative cases.

### M1-T3 — Declarative executor and runner

- Requirements: FR-SRC-02, FR-SRC-05, FR-PERM-02, FR-API-02 (ordering), NFR-PERF-03
- Depends on: M1-T2
- Scope: `engine/doctype_query.py`, `engine/runner.py`; tests.
- Do: §4.4 and §4.7: placeholders, count pass with cap and derived counters (`urgent`, `immediate`, `overdue`, `latest`, `new_since`), items pass with ordering and pagination, fault isolation and logging, count cache with TTL.
- Acceptance: permission tests prove exclusion by role permission, by a User Permission, and by a `permission_query_conditions` function on a test DocType created inside the test module; cap behaviour at 99/100+; ordering overdue → priority → date; a raising source yields `state: error` without affecting others; logs contain no titles.

### M1-T4 — Built-in sources

- Requirements: FR-SRC-04, FR-PERM-03
- Depends on: M1-T3
- Scope: `sources/approvals.py`, `sources/builtin.py`, hook registration of the three built-ins in this app's own `hooks.py`; tests.
- Do: §4.5, including `route_fields` support in the declarative definition.
- Acceptance: approvals tests build a real Workflow on a test DocType and prove: role holder with read permission sees the item once per document; role holder without read permission on the document sees nothing and count 0; completed actions disappear. Assignments and notifications tests cover mapping, priority, due/overdue, routes and "other users' rows are invisible".

### M1-T5 — Server API, preferences and bootinfo

- Requirements: FR-API-01..04, FR-PERM-01, FR-SET-02, NFR-SEC-01, NFR-PERF-02
- Depends on: M1-T4
- Scope: `api.py`, `engine/preferences.py`, `boot.py`; tests.
- Do: §5 in full, including watermarks / `new_since`, `should_auto_open` via session-id hash, effective preferences (defaults + overrides), `test_source` for managers.
- Acceptance: tests for every endpoint: happy path, invalid input, invisible source rejected, Guest rejected, no way to read or write another user's data; `extend_bootinfo` never raises (tested with a forced failure) and performs no source query.

### M2-T1 — Realtime nudges

- Requirements: FR-RT-01, FR-RT-03, FR-PERM-05
- Depends on: M1-T5
- Scope: `engine/realtime.py`, `engine/recipients.py`, `hooks.py` doc_events; tests.
- Do: §6 in full.
- Acceptance: with `frappe.publish_realtime` patched, tests prove: unwatched DocType takes the fast path (assert the slow path is not entered); one nudge per user per request for multiple changes; payload has only `sources`, `actor`, optional `broadcast`; previous and new assignee are both nudged on reassignment; count cache invalidated for recipients; broadcast path above the audience cap; `nudge()` works and validates the source key.

### M3-T1 — Client skeleton and launcher

- Requirements: FR-UI-01, FR-UI-05, FR-UI-06, FR-UI-09 (structure), FR-UI-10, NFR-REL-01, NFR-PERF-02
- Depends on: M2-T1
- Scope: `public/js/attention_center/` (`index.js`, `store.js`, `api.js`, `ui/styles.js`, `ui/icons.js`, `ui/launcher.js`, `util/*`), `attention_center.bundle.js`, `hooks.py` (`app_include_js`), `tests/js/`, `scripts/ci/run_tests.sh` (add `node --test`).
- Do: §7.1 and the launcher part of §7.2: Shadow DOM host, token stylesheet per `docs/DESIGN_TOKENS.md` (light and dark), launcher with count / unseen dot / collapse (persisted through `set_preferences`), title counter, first summary fetch after boot. Clicking the launcher may show a placeholder until M3-T2.
- Acceptance: `bench build --app attention_center` succeeds; unit tests for store, escaping, route validation and title-counter logic run with `node --test`; a forced exception during boot leaves the desk working (tested by unit-testing the guard); bundle size reported in the PR and within NFR-PERF-02.

### M3-T2 — Window in dialog mode

- Requirements: FR-UI-02, FR-UI-08, FR-API-03 (client side)
- Depends on: M3-T1
- Scope: `attention_center_window.bundle.js`, `ui/window.js`, `ui/tabs.js`, `ui/table.js`.
- Do: lazy-loaded window: tabs with counters ("All", one per action source, info sources), table with the columns of FR-UI-02, pagination, loading/empty/error states, "Open" navigation, "View all", `mark_seen` on tab view, focus trap, `Esc`, keyboard shortcut, ARIA roles, live region.
- Acceptance: unit tests for sorting/merging in the "All" tab, pagination state and keyboard roving logic; manual verification notes with a screenshot (Playwright if available per `docs/SANDBOX.md`) attached to the PR description in Arabic RTL and English LTR.

### M3-T3 — Panel and drawer modes, responsive rows

- Requirements: FR-UI-03, FR-UI-04
- Depends on: M3-T2
- Scope: `ui/window.js`, `ui/styles.js`, `ui/table.js`.
- Do: §7.2 containers and stacked-row layout; display mode from effective preferences; switching mode without reload.
- Acceptance: the same content renders in the three modes; stacked rows below 720 px and at 360 px without horizontal scrolling; screenshots of the three modes in RTL in the PR.

### M3-T4 — Refresh loop

- Requirements: FR-RT-02
- Depends on: M3-T3
- Scope: `realtime.js`, `store.js`.
- Do: §7.3: nudge listener with broadcast jitter, visibility / reconnect / online / heartbeat refresh, debouncing and request de-duplication, summary diff exposed to the alert layer.
- Acceptance: unit tests with a fake clock and fake event sources prove: bursts cause one request; hidden tabs do not poll; heartbeat honours the configured interval; an in-flight request is not duplicated.

### M4-T1 — Alert policy and toasts

- Requirements: FR-ALERT-01..04, FR-UI-07
- Depends on: M3-T4
- Scope: `alerts/policy.js`, `alerts/coalesce.js`, `ui/toast.js`.
- Do: §7.4 first two bullets; toasts per FR-UI-07; sticky toast for `immediate`.
- Acceptance: table-driven unit tests cover every row of FR-ALERT-02 for each sound scope, self-suppression, DND, coalescing (highest class wins), and "first summary after load produces no new-item alert".

### M4-T2 — Sound engine

- Requirements: FR-SND-01..04
- Depends on: M4-T1
- Scope: `alerts/sound.js`, `alerts/tabs.js`, `public/sounds/tones.json` consumption, settings select options for tones.
- Do: §7.5 in full. Use the committed tone files and `tones.json`; do not regenerate or replace audio.
- Acceptance: unit tests with fake `Audio`, channel, storage and clock prove: mute and DND precedence; locked-audio flow and unlock on first gesture; exactly one of three simulated tabs plays an alert, and a visible tab wins; volume mapping.

### M4-T3 — Login auto-open and periodic reminder

- Requirements: FR-ALERT-05, FR-ALERT-06
- Depends on: M4-T2
- Scope: `alerts/reminder.js`, `index.js`, `ui/window.js` (summary line).
- Do: §7.4 last two bullets.
- Acceptance: unit tests: auto-open happens once per session marker and only with action items; disabled by preference; reminder fires once per interval across simulated tabs, only while attention items exist, never opens the window.

### M5-T1 — User settings view

- Requirements: FR-SND-02, FR-SET-02, FR-UI-03
- Depends on: M4-T3
- Scope: `ui/settings.js`, small additions to `api.py` if validation gaps appear.
- Do: settings view inside the window: sound scope, tone with preview, volume, Do Not Disturb (1 hour / until end of day / off), auto-open, display mode. Changes apply immediately and persist.
- Acceptance: unit tests for the settings state machine and DND computation; backend tests for any new validation; no control exists that disables the badge or the urgent visuals.

### M5-T2 — Admin forms and bell option

- Requirements: FR-SRC-02 (AC2), FR-SET-01, FR-SET-03
- Depends on: M5-T1
- Scope: form scripts for `Attention Source` and `Attention Center Settings`, `hide_standard_bell`, a small workspace or desk shortcut for managers.
- Do: field visibility by source type; "Test for my user" button calling `test_source`; tone selects populated from `tones.json`; optional CSS rule hiding the stock navbar bell when the setting is on.
- Acceptance: backend tests for `test_source` permissions; a non-manager cannot open the forms; documented manual check of the forms in the PR.

### M6-T1 — Arabic, RTL, dark mode and UI smoke tests

- Requirements: FR-UI-09, FR-UI-10, NFR-I18N-01, NFR-A11Y-01
- Depends on: M5-T2
- Scope: `translations/ar.csv`, style fixes, `tests/` translation-completeness test, Playwright smoke tests under `tests/ui/` wired into `scripts/ci/run_tests.sh` (skipped with a clear message if the browser is unavailable).
- Acceptance: the completeness test fails when a wrapped string lacks an Arabic translation; smoke tests open the launcher and window in RTL and LTR, light and dark; contrast of token pairs checked by a small script.

### M6-T2 — Performance, resilience and security pass

- Requirements: NFR-PERF-01..03, NFR-SEC-01..03, NFR-PRIV-01, NFR-REL-01
- Depends on: M6-T1
- Scope: targeted fixes across the app; `scripts/dev/perf_seed.py` and a measurement note in `docs/PERF.md`.
- Do: seed 10 000 rows per built-in source DocType on the sandbox site and measure NFR-PERF-01; review every whitelisted method and every place text is rendered; verify the doc-event fast path.
- Acceptance: measured numbers recorded; any miss either fixed or escalated with data; a test asserts the fast path.

### M6-T3 — Provider guide, example and release 0.1.0

- Requirements: FR-SRC-03 (AC3), success measure 3
- Depends on: M6-T2
- Scope: `docs/PROVIDER_CONTRACT.md`, `examples/` (a minimal consumer app snippet with one declarative and one python source, with tests exercising it through fake hooks), `README.md`, `CHANGELOG.md`, version `0.1.0`.
- Acceptance: a reader can add a source using only the guide; the examples are exercised by tests; README explains install, configuration and limits.

### M7-T1 — Announcements backend

- Requirements: FR-ANN-01, FR-ANN-03, FR-ANN-04 (data), FR-PERM-04
- Depends on: M6-T3
- Scope: §3.4 DocTypes, audience resolution, sanitising, receipts, built-in announcements source, API (`acknowledge_announcement`, manager receipt list); tests.
- Acceptance: audience tests (all / roles / groups) with negative cases; validity window; acknowledgement stored once; receipts visible to managers only; unacknowledged required announcements count as action items.

### M7-T2 — Announcements UI

- Requirements: FR-ANN-02, FR-ANN-03, FR-ANN-04
- Depends on: M7-T1
- Scope: Announcements tab, detail view, acknowledge control, sticky toast for `immediate`, manager receipt view (desk report or form section) with export.
- Acceptance: unit tests for tab logic; backend tests for the report's permission; screenshots in RTL.

### M7-T3 — Remind me later and extra sources

- Requirements: FR-SNZ-01, FR-EXT-01
- Depends on: M7-T2
- Scope: snooze control on rows using Frappe's `Reminder`; built-in info sources for today's events and due reminders.
- Acceptance: tests prove a reminder is created for the right user and document and that the extra sources respect permissions.

### M7-T4 — Source health and release 0.2.0

- Requirements: FR-EXT-02
- Depends on: M7-T3
- Scope: lightweight recording of last error and rolling duration per source (cache-backed, no item data), manager view, final polish, version `0.2.0`, `CHANGELOG.md`.
- Acceptance: tests for recording and permissions; documentation updated; after merge the pipeline reports `DONE`.
