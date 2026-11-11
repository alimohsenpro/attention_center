import json
import time
from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from attention_center.engine import registry, runner
from attention_center.tests.utils import make_desk_role, make_user

SOURCE = "Attention Source"
SETTINGS = "Attention Center Settings"
# Document content that must never reach a log.
SECRET_TITLE = "Quarterly salary review"
NO_COUNTS = {
	"count": 0,
	"capped": False,
	"urgent": 0,
	"immediate": 0,
	"overdue": 0,
	"latest": None,
	"new_since": 0,
}


def count_three(user: str) -> int:
	return 3


def count_with_watermark(user: str, since: datetime | None = None) -> dict:
	return {"count": 4, "new_since": 4 if since is None else 1, "latest": "2026-11-09 10:30:00"}


def count_that_raises(user: str) -> int:
	frappe.throw(f"Cannot count {SECRET_TITLE}")


def count_of_the_wrong_shape(user: str) -> dict:
	return {"count": "four"}


def count_slowly(user: str) -> int:
	return frappe.db.sql("select sleep(1)")[0][0]


def items_of_the_user(user: str, start: int, page_length: int) -> list[dict]:
	"""One more item than asked for, and one without a title."""
	numbers = range(start, start + page_length + 1)
	return [{"id": "untitled", "route": "/app/todo"}] + [
		{"id": f"{user}:{number}", "title": f"Item {number}", "route": f"/app/todo/{number}"}
		for number in numbers
	]


def items_that_raise(user: str, start: int, page_length: int) -> list[dict]:
	raise ValueError(SECRET_TITLE)


def items_not_in_a_list(user: str, start: int, page_length: int) -> dict:
	return {"items": []}


def add_python_source(key: str, get_count: str, get_items: str = "items_of_the_user") -> frappe._dict:
	doc = frappe.get_doc(
		{
			"doctype": SOURCE,
			"key": key,
			"label": key,
			"kind": "Action",
			"source_type": "Python",
			"is_system": 1,
			"app": "attention_center",
			"get_count": f"{__name__}.{get_count}",
			"get_items": f"{__name__}.{get_items}",
		}
	)
	# The hook sync is the only way to declare a python source; this stands in for it.
	doc.flags.from_hooks = True
	doc.insert()
	return source_row(key)


def add_todo_source(key: str) -> frappe._dict:
	frappe.get_doc(
		{
			"doctype": SOURCE,
			"key": key,
			"label": key,
			"kind": "Action",
			"source_type": "DocType Query",
			"reference_doctype": "ToDo",
			"title_field": "description",
			"date_field": "creation",
			"filters_json": json.dumps([["status", "=", "Open"], ["allocated_to", "=", "{user}"]]),
		}
	).insert()
	return source_row(key)


def source_row(key: str) -> frappe._dict:
	return frappe.db.get_value(SOURCE, key, list(registry.SOURCE_FIELDS), as_dict=True)


def add_todo(user: str, description: str = "Prepare the agenda") -> None:
	frappe.get_doc({"doctype": "ToDo", "description": description, "allocated_to": user}).insert(
		ignore_permissions=True
	)


def logger():
	return frappe.logger("attention_center")


class TestRunner(FrappeTestCase):
	def setUp(self):
		role = make_desk_role("_Test Attention Runner")
		self.user = make_user("runner.user@example.com", [role])
		self.other_user = make_user("runner.other@example.com", [role])
		self.keys = []
		frappe.set_user(self.user)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		for key in self.keys:
			frappe.cache.delete_value(runner.COUNT_CACHE.format(key))

	def python_source(self, key: str, get_count: str, get_items: str = "items_of_the_user") -> frappe._dict:
		self.keys.append(key)
		frappe.set_user("Administrator")
		try:
			return add_python_source(key, get_count, get_items)
		finally:
			frappe.set_user(self.user)

	def todo_source(self, key: str) -> frappe._dict:
		self.keys.append(key)
		frappe.set_user("Administrator")
		try:
			return add_todo_source(key)
		finally:
			frappe.set_user(self.user)

	def test_a_failing_source_is_an_error_and_the_others_still_run(self):
		failing = self.python_source("test_app.failing", "count_that_raises", "items_that_raise")
		todos = self.todo_source("test_app.todos")
		three = self.python_source("test_app.three", "count_three")
		add_todo(self.user)
		messages_before = list(frappe.local.message_log)

		with self.assertLogs(logger(), "ERROR") as logs:
			counts = {source.key: runner.run_count(source, self.user) for source in (failing, todos, three)}
			items = {source.key: runner.run_items(source, self.user, 0, 5) for source in (failing, todos)}

		self.assertEqual(counts["test_app.failing"], {"state": "error", **NO_COUNTS})
		self.assertEqual((counts["test_app.todos"]["state"], counts["test_app.todos"]["count"]), ("ok", 1))
		self.assertEqual((counts["test_app.three"]["state"], counts["test_app.three"]["count"]), ("ok", 3))
		self.assertEqual(items["test_app.failing"], {"state": "error", "items": []})
		self.assertEqual([item["title"] for item in items["test_app.todos"]["items"]], ["Prepare the agenda"])
		self.assertEqual(frappe.local.message_log, messages_before, "a failed source opens no dialog")
		self.assertEqual(len(logs.output), 2)
		self.assertRegex(
			logs.output[0],
			rf"source test_app\.failing failed for {self.user} after \d+ ms: ValidationError$",
		)
		self.assertRegex(logs.output[1], r"source test_app\.failing failed .*: ValueError$")
		self.assertNotIn(SECRET_TITLE, "\n".join(logs.output))

	def test_a_python_source_breaking_the_contract_is_an_error(self):
		wrong_count = self.python_source(
			"test_app.wrong_count", "count_of_the_wrong_shape", "items_not_in_a_list"
		)

		with self.assertLogs(logger(), "ERROR") as logs:
			counts = runner.run_count(wrong_count, self.user)
			items = runner.run_items(wrong_count, self.user, 0, 5)

		self.assertEqual(counts["state"], "error")
		self.assertEqual(items, {"state": "error", "items": []})
		self.assertIn("ContractError: the count must be a whole number", logs.output[0])
		self.assertIn("ContractError: source test_app.wrong_count returned dict", logs.output[1])

	def test_a_python_source_whose_statement_overruns_the_budget_is_stopped_and_the_timeout_restored(self):
		slow = self.python_source("test_app.slow", "count_slowly")
		timeout_before = frappe.db.sql("select @@session.max_statement_time")[0][0]

		with patch.object(runner, "TIME_BUDGET_SECONDS", 0.2), self.assertLogs(logger(), "ERROR") as logs:
			started = time.monotonic()
			result = runner.run_count(slow, self.user)
			elapsed = time.monotonic() - started

		self.assertEqual(result, {"state": "error", **NO_COUNTS})
		self.assertLess(elapsed, 0.9, "the one-second sleep must have been interrupted")
		self.assertRegex(
			logs.output[0], rf"source test_app\.slow failed for {self.user} after \d+ ms: \w+Error$"
		)
		self.assertEqual(frappe.db.sql("select @@session.max_statement_time")[0][0], timeout_before)

	def test_a_python_source_gets_the_user_the_page_and_the_watermark_it_accepts(self):
		with_watermark = self.python_source("test_app.with_watermark", "count_with_watermark")
		without_watermark = self.python_source("test_app.without_watermark", "count_three")
		watermark = datetime(2026, 11, 9, 12, 0)

		self.assertEqual(
			runner.run_count(with_watermark, self.user),
			{**NO_COUNTS, "state": "ok", "count": 4, "new_since": 4, "latest": "2026-11-09T10:30:00"},
		)
		self.assertEqual(runner.run_count(with_watermark, self.user, since=watermark)["new_since"], 1)
		self.assertEqual(runner.run_count(without_watermark, self.user, since=watermark)["count"], 3)

		with self.assertLogs(logger(), "WARNING"):
			page = runner.run_items(with_watermark, self.user, 2, 3)
		self.assertEqual(
			[item["id"] for item in page["items"]], [f"{self.user}:2", f"{self.user}:3", f"{self.user}:4"]
		)

	def test_counts_are_cached_per_user_until_the_ttl_passes(self):
		todos = self.todo_source("test_app.todos")
		add_todo(self.user)
		self.assertEqual(runner.run_count(todos, self.user)["count"], 1)

		add_todo(self.user, "Book the room")
		self.assertEqual(runner.run_count(todos, self.user)["count"], 1, "served from the cache")
		frappe.set_user(self.other_user)
		self.assertEqual(runner.run_count(todos, self.other_user)["count"], 0, "not the first user's entry")
		frappe.set_user(self.user)

		ttl = frappe.get_cached_doc(SETTINGS).summary_cache_ttl
		with patch.object(runner, "time") as clock:
			clock.time.return_value = time.time() + ttl + 1
			self.assertEqual(runner.run_count(todos, self.user)["count"], 2)

	def test_the_ttl_comes_from_the_settings(self):
		frappe.set_user("Administrator")
		settings = frappe.get_single(SETTINGS)
		settings.summary_cache_ttl = 5
		settings.save()
		frappe.set_user(self.user)
		todos = self.todo_source("test_app.todos")
		runner.run_count(todos, self.user)
		add_todo(self.user)

		with patch.object(runner, "time") as clock:
			clock.time.return_value = time.time() + 4
			self.assertEqual(runner.run_count(todos, self.user)["count"], 0)
			clock.time.return_value = time.time() + 6
			self.assertEqual(runner.run_count(todos, self.user)["count"], 1)

	def test_a_new_watermark_is_not_served_from_the_cache(self):
		with_watermark = self.python_source("test_app.with_watermark", "count_with_watermark")

		self.assertEqual(runner.run_count(with_watermark, self.user)["new_since"], 4)
		self.assertEqual(
			runner.run_count(with_watermark, self.user, since=datetime(2026, 11, 9))["new_since"], 1
		)
		self.assertEqual(runner.run_count(with_watermark, self.user)["new_since"], 4)

	def test_a_failed_count_is_cached_like_any_other(self):
		source = self.python_source("test_app.flaky", "count_that_raises")
		with self.assertLogs(logger(), "ERROR"):
			self.assertEqual(runner.run_count(source, self.user)["state"], "error")

		source.get_count = f"{__name__}.count_three"
		self.assertEqual(runner.run_count(source, self.user)["state"], "error")
		with patch.object(runner, "time") as clock:
			clock.time.return_value = time.time() + frappe.get_cached_doc(SETTINGS).summary_cache_ttl + 1
			self.assertEqual(runner.run_count(source, self.user)["count"], 3)

	def test_a_slow_source_is_logged_with_its_key_user_and_duration(self):
		three = self.python_source("test_app.three", "count_three")

		with patch.object(runner, "perf_counter", side_effect=[10.0, 12.5]):
			with self.assertLogs(logger(), "WARNING") as logs:
				result = runner.run_count(three, self.user)

		self.assertEqual((result["state"], result["count"]), ("ok", 3))
		self.assertEqual(len(logs.output), 1)
		self.assertIn(f"source test_app.three was slow for {self.user}: 2500 ms", logs.output[0])

	def test_a_source_within_its_budget_logs_nothing(self):
		three = self.python_source("test_app.three", "count_three")

		with self.assertNoLogs(logger(), "WARNING"):
			self.assertEqual(runner.run_count(three, self.user)["state"], "ok")
