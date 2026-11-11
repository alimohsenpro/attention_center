# Attention Center — Performance

Measured by task M6-T2 on 2026-11-11 in the agents' cloud sandbox, against NFR-PERF-01..03 and the
document-event fast path (FR-RT-01 AC1, §11 of `docs/TECH_DESIGN.md`). `scripts/dev/perf_seed.py`
builds the dataset and takes every number below; run it again after a change that may move them.

## Verdict

| Requirement | Target | Measured | |
|---|---|---|---|
| NFR-PERF-01, warm | p95 ≤ 200 ms | p95 ≤ 10 ms | met |
| NFR-PERF-01, cold | p95 ≤ 800 ms | p95 ≤ 195 ms; ≤ 544 ms even after `bench clear-cache` | met |
| NFR-PERF-02, launcher bundle | ≤ 25 KB gzipped | 10.5 KB; the window's 12.2 KB load on first open | met |
| NFR-PERF-02, desk boot | no blocking request | no request; the app's part of the boot takes ≤ 1.1 ms (p95) | met |
| NFR-PERF-03 | capped queries, a time budget | 100 rows per count query; every statement of every source stopped after 2 s | met |
| FR-RT-01 AC1 | O(1) for an unwatched DocType | 7 µs per event, no query, no Redis round trip | met |

Nothing missed its target, so nothing was escalated.

## How to measure

```bash
cd ~/frappe-bench
env/bin/python /workspace/attention_center/scripts/dev/perf_seed.py seed      # 7 s; removes an earlier seed first
env/bin/python /workspace/attention_center/scripts/dev/perf_seed.py measure   # 46 s; prints the table below
env/bin/python /workspace/attention_center/scripts/dev/perf_seed.py clear     # removes the users, roles and rows
```

`BENCH_DIR` and `SITE` override `~/frappe-bench` and `test_site`. Use a throwaway site only: `seed`
creates 50 users. The backend tests pass with the dataset present; CI never seeds it.

## Environment

The sandbox of `docs/SANDBOX.md`: 4 vCPU, 16 GB, Ubuntu 24.04, Python 3.11.17, Frappe 15.126.1,
MariaDB 10.11.14 and Redis 7.0.15 on the same machine, default site configuration. Requests go to
`bench serve` (Werkzeug, one process), one after the other, from one client on the same machine: the
numbers are response times, not throughput under load. A production bench (gunicorn behind nginx)
does the same work per request.

## Dataset

The reference dataset of NFR-PERF-01, 10 000 rows of each built-in source DocType, spread over 50
desk users (200 rows each, the newest a minute apart):

- `ToDo`: per user 150 open (priority Low, Medium and High in turn, due dates from two days ago to
  four days ahead, so some are overdue) and 50 closed.
- `Notification Log`: per user 120 unread and 80 read, each about one of the user's assignments.
- `Workflow Action`: one per assignment, open while the assignment is, waiting on a role only that
  user holds (10 000 rows of `Workflow Action Permitted Role`), on a document the user may read.

The measured user therefore sees 99+ in all three sources, the most work a summary does: each
source's capped query reads its newest 100 rows, and the approvals source loads 100 documents and
checks read permission on each (§4.5). The rows are bulk inserts, which raise no document events.

## Results

`perf_seed.py measure`, three runs in a row. p50 and max are from run 1; p95 from each run.

| Measured | n | p50 ms | p95 ms (runs 1, 2, 3) | max ms |
|---|---|---|---|---|
| `frappe.auth.get_logged_user` (Frappe's request overhead), warm | 100 | 5.9 | 7.5, 7.4, 8.3 | 10.6 |
| `get_summary`, warm | 100 | 6.8 | 8.6, 9.4, 10.3 | 10.0 |
| `get_summary`, cold: no cached count or visible source | 50 | 149 | 189, 178, 179 | 191 |
| `get_summary`, cold, the user's Frappe caches dropped too (as after a role change) | 50 | 158 | 195, 187, 194 | 203 |
| `get_summary` after `bench clear-cache`: the whole site cache dropped | 50 | 437 | 544, 542, 516 | 592 |
| `get_items` approvals, first page of 10 | 30 | 42 | 57, 56, 60 | 71 |
| `get_items` assignments, first page of 10 | 30 | 17 | 22, 25, 26 | 30 |
| `get_items` notifications, first page of 10 | 30 | 12 | 15, 16, 18 | 20 |
| `run_count` approvals, in process, not cached | 20 | 99 | 126, 133, 139 | 134 |
| `run_count` assignments, in process, not cached | 20 | 8.1 | 10.8, 13.0, 12.3 | 13.6 |
| `run_count` notifications, in process, not cached | 20 | 2.9 | 4.0, 5.4, 5.3 | 5.8 |
| `extend_bootinfo`, in process | 100 | 0.65 | 0.93, 0.97, 1.11 | 1.70 |
| `on_doc_event` on an unwatched DocType, in process, per event (10 000 events a run) | 20 | 0.0066 | 0.013, 0.008, 0.007 | 0.014 |

What the rows mean:

- **Warm**: every source's count is in the per-user cache, as for the heartbeat and any summary within
  `summary_cache_ttl` (60 s) of the last one (§4.7).
- **Cold**, the case of NFR-PERF-01: before each request the app's caches are dropped (every count, the
  visible sources, the watch map), as when the TTL has passed: every source runs.
- **Cold, user caches dropped**: also `frappe.clear_cache(user=…)` (roles, permissions, defaults), which
  Frappe does whenever the user is saved, a change of their roles included.
- **After `bench clear-cache`**: `frappe.clear_cache()`, the whole site cache including every DocType's
  meta. Not the cold of NFR-PERF-01, which is about the summary's own cache, but within its 800 ms too.

## Where the time goes

- A cold summary is mostly the approvals source: about 100 to 140 ms for its 100 document loads and
  permission checks, against 3 to 13 ms for each declarative source. The cost grows with the
  permission hooks of the DocTypes under workflow, and is paid once per user per TTL (§11).
- A warm summary costs 1 to 2 ms more than Frappe's lightest endpoint: one preference row, the
  cached settings and visible sources, and one Redis read per source.
- The window's pages (`get_items`) are not cached; their worst first page, approvals, answers within
  60 ms (p95).

## NFR-PERF-02: bundles and boot

- The launcher bundle, loaded on every desk page, is 27.5 KB minified and 10.5 KB gzipped
  (`gzip -9`; 11.6 KB at `-1`). The window bundle, 36.8 KB and 12.2 KB gzipped, is loaded on the
  first opening (§7.1). `test_install.py` fails when the launcher bundle passes 25 KB gzipped or carries
  the window's code.
- The boot sends no request: `extend_bootinfo` reads the cached settings and one preference row and
  runs no source (§5, `test_boot.py`); the first summary is fetched 1.5 s after `app_ready` (§7.3).

## NFR-PERF-03: caps and time budget

- Every count query reads at most 100 rows: the declarative query (§4.4) and the approvals query of
  `Workflow Action` (§4.5). A python source of another app caps its own query; the engine caps the
  numbers it reports at 99.
- Since M6-T2 the runner runs every source, declarative or python, under a 2 s statement timeout
  (`max_statement_time`), so no single query of a source runs longer; a stopped statement fails the
  source, which the summary reports with `state: "error"` (§4.7; `test_runner.py`,
  `test_doctype_query.py`). Before, a python source's queries, the approvals source's included, ran
  without a limit.
- Limit: a python source that spends its time in many quick statements or in Python is not stopped;
  it is logged as slow once it takes over 2 s in all.

## Document-event fast path

Every document event of every DocType reaches `realtime.on_doc_event`. For a DocType no enabled source
watches it costs about 7 µs: three flag checks and a lookup in the request's copy of the watch map.
The first event of a request reads the map from Redis once; the map is rebuilt from the database at
most every 5 minutes, or after a source, the settings or a workflow change (§6).
`test_realtime.py::test_an_unwatched_doctype_takes_the_fast_path` fails when such an event reaches
the slow path, runs a query, or makes a Redis round trip once the request holds the map.
