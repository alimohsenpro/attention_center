"""The reference dataset of NFR-PERF-01, and the measurement of the summary on it (docs/PERF.md).

Run it with the bench's Python, on a throwaway site such as the sandbox's test_site:

	cd ~/frappe-bench
	env/bin/python /path/to/attention_center/scripts/dev/perf_seed.py seed      # 10 000 rows per source DocType
	env/bin/python /path/to/attention_center/scripts/dev/perf_seed.py measure   # serves the site, times requests
	env/bin/python /path/to/attention_center/scripts/dev/perf_seed.py clear     # removes what seed added

BENCH_DIR and SITE override ~/frappe-bench and test_site.

`seed` gives each of USERS desk users ROWS / USERS rows of ToDo, Notification Log and Workflow Action: 150 open
assignments, 120 unread notifications and 150 open workflow actions, which wait on a role only that user holds and
concern the user's own assignments. Every built-in source of every seeded user is past its count cap (99+), the
most work a summary does: the newest 100 rows of each source, and 100 documents loaded and permission-checked by
the approvals source. The rows are written with bulk inserts, which fire no document events.

`measure` logs in as the first seeded user over HTTP (`bench serve`, one process) and times, one request after the
other, get_summary warm and with ever more caches dropped before each request, then the first page of each source's
items. In this process it then times each source's count without its cache, the app's part of the desk boot, and
the document-event handler on a DocType no source watches. It prints a Markdown table of milliseconds.
"""

import http.cookiejar
import math
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

import frappe
from frappe.utils import now_datetime
from frappe.utils.password import update_password

from attention_center import api, boot
from attention_center.engine import preferences, realtime, registry, runner
from attention_center.sources.builtin import SOURCES

BENCH_DIR = Path(os.environ.get("BENCH_DIR", Path.home() / "frappe-bench"))
SITE = os.environ.get("SITE", "test_site")

ROWS = 10_000
USERS = 50
PREFIX = "perf-seed-"
SOURCE_DOCTYPES = ("ToDo", "Notification Log", "Workflow Action", "Workflow Action Permitted Role")
TODO_PRIORITIES = ("Low", "Medium", "High")
# A source's count is capped at 99; from 100 rows on it shows 99+ (contract.COUNT_CAP).
CAPPED_FROM = 100

API = "attention_center.api"
WARM_REQUESTS = 100
COLD_REQUESTS = 50
ITEM_REQUESTS = 30
COUNT_RUNS = 20
EVENTS = 10_000


def user_id(number: int) -> str:
	return f"perf.user{number:02d}@example.com"


def role_name(number: int) -> str:
	return f"Perf Seed Approver {number:02d}"


def seed() -> None:
	clear()
	now = now_datetime()
	# Frappe refuses more than 60 new users an hour unless they are imported. An import skips the defaults on
	# insert, so the documents get them from new_doc.
	frappe.flags.in_import = True
	for number in range(1, USERS + 1):
		frappe.new_doc("Role", role_name=role_name(number), desk_access=1).insert(ignore_permissions=True)
		frappe.new_doc(
			"User",
			email=user_id(number),
			first_name="Perf",
			last_name=f"User {number:02d}",
			send_welcome_email=0,
			roles=[{"role": role_name(number)}],
		).insert(ignore_permissions=True)
		# Older than their rows, as on a real site; that also leaves the hourly limit to a test that adds a user.
		frappe.db.set_value(
			"User", user_id(number), "creation", now - timedelta(minutes=ROWS), update_modified=False
		)
	frappe.flags.in_import = False

	todos, logs, actions, permitted_roles = [], [], [], []
	for row in range(ROWS):
		# Rows alternate between the users, so each user's rows spread over the whole period.
		number = row % USERS + 1
		turn = row // USERS
		when = now - timedelta(minutes=row)
		todo = f"{PREFIX}todo-{row:05d}"
		is_open = turn % 4 != 3
		todos.append(
			{
				**standard(todo, when),
				"status": "Open" if is_open else "Closed",
				"priority": TODO_PRIORITIES[turn % 3],
				"date": (when + timedelta(days=turn % 7 - 2)).date(),
				"allocated_to": user_id(number),
				"assigned_by": "Administrator",
				"description": f"Seeded task {row:05d}",
			}
		)
		logs.append(
			{
				**standard(f"{PREFIX}log-{row:05d}", when),
				"subject": f"Seeded notification {row:05d}",
				"for_user": user_id(number),
				"type": "Alert",
				"document_type": "ToDo",
				"document_name": todo,
				"from_user": "Administrator",
				"read": int(turn % 5 >= 3),
			}
		)
		action = f"{PREFIX}action-{row:05d}"
		actions.append(
			{
				**standard(action, when),
				"status": "Open" if is_open else "Completed",
				"reference_doctype": "ToDo",
				"reference_name": todo,
				"workflow_state": "Pending",
			}
		)
		permitted_roles.append(
			{
				**standard(f"{PREFIX}role-{row:05d}", when),
				"idx": 1,
				"parent": action,
				"parenttype": "Workflow Action",
				"parentfield": "permitted_roles",
				"role": role_name(number),
			}
		)

	for doctype, rows in zip(SOURCE_DOCTYPES, (todos, logs, actions, permitted_roles), strict=True):
		fields = list(rows[0])
		frappe.db.bulk_insert(doctype, fields, [[row[field] for field in fields] for row in rows])
	frappe.db.commit()
	drop_app_caches()
	print(f"Seeded {ROWS} rows of {', '.join(SOURCE_DOCTYPES)} for {USERS} users ({user_id(1)} …).")


def standard(name: str, when: datetime) -> dict:
	stamp = when.strftime("%Y-%m-%d %H:%M:%S.%f")
	return {
		"name": name,
		"owner": "Administrator",
		"modified_by": "Administrator",
		"creation": stamp,
		"modified": stamp,
		"docstatus": 0,
		"idx": 0,
	}


def clear() -> None:
	for doctype in reversed(SOURCE_DOCTYPES):
		frappe.db.delete(doctype, {"name": ("like", f"{PREFIX}%")})
	for number in range(1, USERS + 1):
		if frappe.db.exists("User", user_id(number)):
			frappe.delete_doc("User", user_id(number), force=True, ignore_permissions=True)
		if frappe.db.exists("Role", role_name(number)):
			frappe.delete_doc("Role", role_name(number), force=True, ignore_permissions=True)
	frappe.db.commit()
	drop_app_caches()


def drop_app_caches() -> None:
	"""Every user's cached counts and visible sources, and the watch map."""
	frappe.cache.delete_keys("attention_center:")


def measure() -> None:
	user = user_id(1)
	check_dataset(user)
	password = secrets.token_urlsafe(18)
	update_password(user, password)
	frappe.db.commit()

	with served_site() as base_url:
		results = measure_requests(base_url, user, password)
	results += measure_in_process(user)
	report(results)


def measure_requests(base_url: str, user: str, password: str) -> list[tuple[str, list[float]]]:
	opener = login(base_url, user, password)

	def get(method: str, **args) -> Callable[[], None]:
		query = f"?{urllib.parse.urlencode(args)}" if args else ""
		url = f"{base_url}/api/method/{method}{query}"
		return lambda: opener.open(url, timeout=30).read()

	summary = get(f"{API}.get_summary")
	summary()
	results = [
		(
			"frappe.auth.get_logged_user (request overhead), warm",
			timings(get("frappe.auth.get_logged_user"), WARM_REQUESTS),
		),
		("get_summary, warm", timings(summary, WARM_REQUESTS)),
		(
			"get_summary, cold: no cached count or visible source",
			timings(summary, COLD_REQUESTS, drop_app_caches),
		),
		(
			"get_summary, cold, the user's Frappe caches dropped too (as after a role change)",
			timings(summary, COLD_REQUESTS, lambda: (drop_app_caches(), frappe.clear_cache(user=user))),
		),
		(
			"get_summary, after bench clear-cache: the whole site cache dropped",
			timings(summary, COLD_REQUESTS, frappe.clear_cache),
		),
	]
	for source in SOURCES:
		items = get(f"{API}.get_items", source=source["key"], page_length=10)
		results.append((f"get_items {source['key']}, first page of 10", timings(items, ITEM_REQUESTS)))
	return results


def measure_in_process(user: str) -> list[tuple[str, list[float]]]:
	"""Each source's count without its cache, the boot's share of the desk, and the doc-event fast path."""
	results = []
	frappe.set_user(user)
	watermarks = preferences.get_watermarks(preferences.get_stored())
	for source in registry.get_visible_sources(user):
		cache = runner.COUNT_CACHE.format(source.key)
		count = partial(runner.run_count, source, user, watermarks.get(source.key))
		results.append(
			(
				f"run_count {source.key}, in process, not cached",
				timings(count, COUNT_RUNS, partial(frappe.cache.hdel, cache, user)),
			)
		)
	boot_info = partial(boot.extend_bootinfo, frappe._dict())
	results.append(("extend_bootinfo, in process", timings(boot_info, WARM_REQUESTS)))

	# Note is watched by no built-in source; the request already holds the watch map, as after its first event.
	note = frappe.new_doc("Note", title="Unwatched")
	registry.get_watch_map()

	def events() -> None:
		for _ in range(EVENTS):
			realtime.on_doc_event(note, "on_change")

	per_event = [duration / EVENTS for duration in timings(events, COUNT_RUNS)]
	results.append((f"on_doc_event for an unwatched DocType, in process, per event (of {EVENTS})", per_event))
	frappe.set_user("Administrator")
	return results


def check_dataset(user: str) -> None:
	"""Stop unless every built-in source of the measured user is past its count cap."""
	if not frappe.db.exists("User", user):
		sys.exit("No seeded user: run `perf_seed.py seed` first.")
	drop_app_caches()
	frappe.set_user(user)
	sources = {source["key"]: source for source in api.get_summary()["sources"]}
	frappe.set_user("Administrator")
	for definition in SOURCES:
		source = sources.get(definition["key"])
		if not source or source["state"] != "ok" or not source["capped"]:
			sys.exit(
				f"{definition['key']} is not past its cap for {user}: {source}. Run `perf_seed.py seed` again."
			)
	rows = ", ".join(f"{doctype} {frappe.db.count(doctype)}" for doctype in SOURCE_DOCTYPES)
	print(f"Rows on the site: {rows}. Every built-in source shows 99+ for {user}.")


@contextmanager
def served_site() -> Iterator[str]:
	with socket.socket() as probe:
		probe.bind(("127.0.0.1", 0))
		port = probe.getsockname()[1]
	with tempfile.TemporaryFile() as log:
		server = subprocess.Popen(
			["bench", "--site", SITE, "serve", "--port", str(port), "--noreload"],
			cwd=BENCH_DIR,
			stdout=log,
			stderr=subprocess.STDOUT,
		)
		try:
			base_url = f"http://127.0.0.1:{port}"
			wait_until_serving(base_url, server, log)
			yield base_url
		finally:
			server.terminate()
			server.wait(timeout=10)


def wait_until_serving(base_url: str, server: subprocess.Popen, log) -> None:
	deadline = time.monotonic() + 60
	while time.monotonic() < deadline and server.poll() is None:
		try:
			urllib.request.urlopen(f"{base_url}/api/method/ping", timeout=2)
			return
		except OSError:
			time.sleep(0.5)
	log.seek(0)
	sys.exit(f"bench serve did not answer:\n{log.read().decode(errors='replace')[-2000:]}")


def login(base_url: str, user: str, password: str) -> urllib.request.OpenerDirector:
	opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
	opener.open(
		f"{base_url}/api/method/login",
		data=urllib.parse.urlencode({"usr": user, "pwd": password}).encode(),
		timeout=30,
	)
	return opener


def timings(call: Callable[[], None], runs: int, before: Callable[[], object] | None = None) -> list[float]:
	"""Milliseconds of each of `runs` calls; `before` runs ahead of each call, outside the timing."""
	durations = []
	for _ in range(runs):
		if before:
			before()
		started = time.perf_counter()
		call()
		durations.append((time.perf_counter() - started) * 1000)
	return durations


def percentile(durations: list[float], share: float) -> float:
	"""Nearest rank: the smallest duration at least `share` of the calls did not exceed."""
	ordered = sorted(durations)
	return ordered[math.ceil(share * len(ordered)) - 1]


def report(results: list[tuple[str, list[float]]]) -> None:
	print("| Measured | n | p50 ms | p95 ms | max ms |")
	print("|---|---|---|---|---|")
	for label, durations in results:
		print(
			f"| {label} | {len(durations)} | {percentile(durations, 0.5):.4g} "
			f"| {percentile(durations, 0.95):.4g} | {max(durations):.4g} |"
		)


COMMANDS = {"seed": seed, "measure": measure, "clear": clear}

if __name__ == "__main__":
	if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
		sys.exit(f"usage: perf_seed.py {'|'.join(COMMANDS)}")
	frappe.init(site=SITE, sites_path=str(BENCH_DIR / "sites"))
	frappe.connect()
	try:
		COMMANDS[sys.argv[1]]()
	finally:
		frappe.destroy()
