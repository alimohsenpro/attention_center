import json
import time
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.permissions import add_user_permission
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, getdate, now_datetime, today

from attention_center.attention_center.doctype.attention_source.attention_source import PLACEHOLDERS
from attention_center.engine import doctype_query, registry, runner
from attention_center.engine.doctype_query import resolve_filters
from attention_center.tests.utils import make_desk_role, make_user

SOURCE = "Attention Source"
KEY = "test_app.requests"
# Created in setUpClass and dropped in tearDownClass: DocType changes commit, so a test cannot roll them back.
REQUEST = "Attention Test Request"
READER = "_Test Attention Request Reader"
OWN_READER = "_Test Attention Own Request Reader"
DEFINITION = {
	"reference_doctype": REQUEST,
	"title_field": "subject",
	"from_field": "requested_by",
	"date_field": "received_on",
	"priority_field": "priority",
	"due_field": "due_date",
	"status_field": "status",
	"priority_map_json": json.dumps({"High": "urgent", "Critical": "immediate"}),
	"filters_json": json.dumps([["status", "=", "Open"]]),
}


def confidential_requests_condition(user: str, doctype: str | None = None) -> str:
	"""permission_query_conditions of the test DocType: a confidential request is for its assignee only."""
	return f"(`tab{REQUEST}`.`confidential` = 0 or `tab{REQUEST}`.`assigned_to` = {frappe.db.escape(user)})"


def slow_condition(user: str, doctype: str | None = None) -> str:
	return "sleep(1) = 0"


@contextmanager
def permission_query_conditions(doctype: str, method: str):
	real_get_hooks = frappe.get_hooks

	def get_hooks(hook=None, default="_KEEP_DEFAULT_LIST", app_name=None):
		hooks = real_get_hooks(hook, default, app_name)
		if hook == "permission_query_conditions":
			return {**hooks, doctype: [method]}
		return hooks

	with patch("frappe.get_hooks", side_effect=get_hooks):
		yield


def create_request_doctype() -> None:
	for role in (READER, OWN_READER):
		if not frappe.db.exists("Role", role):
			make_desk_role(role)
	if frappe.db.exists("DocType", REQUEST):
		frappe.delete_doc("DocType", REQUEST, force=True)
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": REQUEST,
			"module": "Custom",
			"custom": 1,
			"fields": [
				{"fieldname": "subject", "fieldtype": "Data", "label": "Subject"},
				{
					"fieldname": "requested_by",
					"fieldtype": "Link",
					"options": "User",
					"label": "Requested By",
				},
				{"fieldname": "received_on", "fieldtype": "Datetime", "label": "Received On"},
				{
					"fieldname": "priority",
					"fieldtype": "Select",
					"options": "Low\nMedium\nHigh\nCritical",
					"label": "Priority",
				},
				{"fieldname": "due_date", "fieldtype": "Date", "label": "Due Date"},
				{"fieldname": "status", "fieldtype": "Select", "options": "Open\nClosed", "label": "Status"},
				{"fieldname": "assigned_to", "fieldtype": "Link", "options": "User", "label": "Assigned To"},
				{"fieldname": "confidential", "fieldtype": "Check", "label": "Confidential"},
			],
			"permissions": [{"role": READER, "read": 1}, {"role": OWN_READER, "read": 1, "if_owner": 1}],
		}
	).insert()


def add_source(**values) -> frappe._dict:
	frappe.get_doc(
		{
			"doctype": SOURCE,
			"key": KEY,
			"label": "Requests",
			"kind": "Action",
			"source_type": "DocType Query",
			**DEFINITION,
			**values,
		}
	).insert()
	return frappe.db.get_value(SOURCE, KEY, list(registry.SOURCE_FIELDS), as_dict=True)


def add_request(subject: str, owner: str | None = None, **values) -> str:
	doc = frappe.get_doc(
		{"doctype": REQUEST, "subject": subject, "status": "Open", "received_on": now_datetime(), **values}
	).insert(ignore_permissions=True)
	if owner:
		frappe.db.set_value(REQUEST, doc.name, "owner", owner, update_modified=False)
	return doc.name


def logger():
	return frappe.logger("attention_center")


class TestResolveFilters(FrappeTestCase):
	def test_placeholders_are_replaced_inside_values_only(self):
		user = "reader@example.com"
		cases = {
			"user": (["assigned_to", "=", "{user}"], ["assigned_to", "=", user]),
			"today": (["due_date", "<=", "{today}"], ["due_date", "<=", today()]),
			"inside text": (["subject", "like", "%{user}%"], ["subject", "like", f"%{user}%"]),
			"in a list": (
				["owner", "in", ["{user}", "x@example.com"]],
				["owner", "in", [user, "x@example.com"]],
			),
			"field and operator untouched": (["{user}", "{today}", "set"], ["{user}", "{today}", "set"]),
			"unknown placeholder": (["subject", "=", "{name}"], ["subject", "=", "{name}"]),
			"number": (["confidential", "=", 0], ["confidential", "=", 0]),
			"None": (["due_date", "=", None], ["due_date", "=", None]),
		}
		for case, (condition, expected) in cases.items():
			with self.subTest(case):
				self.assertEqual(resolve_filters([condition], user), [expected])

	def test_a_replaced_value_is_not_resolved_again(self):
		self.assertEqual(
			resolve_filters([["subject", "=", "{user}"]], "{today}@example.com"),
			[["subject", "=", "{today}@example.com"]],
		)

	def test_every_placeholder_the_source_form_accepts_is_resolved(self):
		for placeholder in PLACEHOLDERS:
			with self.subTest(placeholder):
				[[_, _, value]] = resolve_filters([["subject", "=", placeholder]], "reader@example.com")
				self.assertNotIn(placeholder, value)


class TestDocTypeQuery(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_request_doctype()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		frappe.delete_doc("DocType", REQUEST, force=True)
		for role in (READER, OWN_READER):
			frappe.delete_doc("Role", role, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		self.reader = make_user("request.reader@example.com", [READER])
		self.other_reader = make_user("other.reader@example.com", [READER])

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.cache.delete_value(runner.COUNT_CACHE.format(KEY))
		# User Permissions are cached per user and a rollback does not clear the cache.
		frappe.cache.delete_value("user_permissions")

	def counts(self, user: str, source: frappe._dict, since: datetime | None = None) -> dict:
		frappe.set_user(user)
		try:
			return doctype_query.get_count(source, user, since)
		finally:
			frappe.set_user("Administrator")

	def summary(self, user: str, source: frappe._dict) -> dict:
		frappe.cache.delete_value(runner.COUNT_CACHE.format(KEY))
		frappe.set_user(user)
		try:
			result = runner.run_count(source, user)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(result["state"], "ok")
		return result

	def items(self, user: str, source: frappe._dict, start: int = 0, page_length: int = 50) -> list[dict]:
		frappe.set_user(user)
		try:
			result = runner.run_items(source, user, start, page_length)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(result["state"], "ok")
		return result["items"]

	def titles(self, user: str, source: frappe._dict, start: int = 0, page_length: int = 50) -> list[str]:
		return [item["title"] for item in self.items(user, source, start, page_length)]

	def test_items_carry_the_mapped_fields(self):
		sender = make_user("request.sender@example.com", [READER])
		due = add_days(getdate(), -1)
		name = add_request(
			"<p>Review the <b>budget</b></p>",
			received_on=datetime(2026, 11, 9, 9, 30),
			requested_by=sender,
			priority="High",
			due_date=due,
		)
		source = add_source()

		self.assertEqual(
			self.items(self.reader, source),
			[
				{
					"id": name,
					"title": "Review the budget",
					"route": f"/app/attention-test-request/{name}",
					"type_label": None,
					"from_label": "request.sender",
					"date": "2026-11-09T09:30:00",
					"priority": "urgent",
					"due": due.isoformat(),
					"overdue": True,
					"status_label": "Open",
					"status_color": "gray",
				}
			],
		)

	def test_the_count_pass_derives_every_counter(self):
		now = now_datetime()
		newest = add_to_date(now, hours=-1)
		add_request("Overdue and urgent", received_on=newest, priority="High", due_date=add_days(today(), -1))
		add_request(
			"Immediate", received_on=add_to_date(now, hours=-2), priority="Critical", due_date=today()
		)
		add_request("Normal", received_on=add_to_date(now, hours=-3), priority="Low")
		add_request(
			"Older, due today", received_on=add_to_date(now, days=-4), priority="Medium", due_date=today()
		)
		add_request("Closed", status="Closed", priority="Critical", due_date=add_days(today(), -1))
		source = add_source()

		self.assertEqual(
			self.counts(self.reader, source, since=add_to_date(now, hours=-2, minutes=-30)),
			{"count": 4, "urgent": 1, "immediate": 1, "overdue": 1, "latest": newest, "new_since": 2},
		)
		self.assertEqual(self.counts(self.reader, source)["new_since"], 4, "no watermark: every row is new")

	def test_a_date_field_compares_with_the_watermark_from_midnight(self):
		add_request("Due yesterday", due_date=add_days(today(), -1))
		add_request("Due today", due_date=today())
		source = add_source(date_field="due_date", due_field=None)
		start_of_today = datetime.combine(getdate(), datetime.min.time())

		counts = self.counts(self.reader, source, since=add_to_date(start_of_today, seconds=-1))

		self.assertEqual((counts["latest"], counts["new_since"]), (start_of_today, 1))

	def test_the_count_is_capped_at_99_and_flagged_from_100_rows_on(self):
		source = add_source()
		for number in range(99):
			add_request(f"Request {number}")
		self.assertEqual(self.summary(self.reader, source)["count"], 99)
		self.assertFalse(self.summary(self.reader, source)["capped"])

		add_request("Request 99")
		self.assertEqual(self.summary(self.reader, source)["count"], 99)
		self.assertTrue(self.summary(self.reader, source)["capped"])

	def test_items_come_overdue_first_then_by_priority_then_newest(self):
		now = now_datetime()
		yesterday = add_days(today(), -1)
		for subject, hours_ago, priority, due in (
			("Normal, newest", 1, "Low", None),
			("Urgent", 2, "High", None),
			("Immediate, newer", 3, "Critical", None),
			("Normal, due today", 4, "Low", today()),
			("Immediate, older", 5, "Critical", None),
			("Overdue, normal", 6, "Medium", yesterday),
			("Overdue, urgent", 8, "High", yesterday),
		):
			add_request(
				subject, received_on=add_to_date(now, hours=-hours_ago), priority=priority, due_date=due
			)
		source = add_source()
		expected = [
			"Overdue, urgent",
			"Overdue, normal",
			"Immediate, newer",
			"Immediate, older",
			"Urgent",
			"Normal, newest",
			"Normal, due today",
		]

		self.assertEqual(self.titles(self.reader, source), expected)
		pages = [self.titles(self.reader, source, start, 3) for start in (0, 3, 6, 9)]
		self.assertEqual(pages, [expected[0:3], expected[3:6], expected[6:7], []])

	def test_rows_past_the_window_follow_by_date_and_every_row_is_listed_once(self):
		now = now_datetime()
		for number in range(doctype_query.WINDOW):
			add_request(f"Recent {number:03}", received_on=add_to_date(now, minutes=-number))
		for number in range(3):
			add_request(
				f"Old, immediate {number}",
				received_on=add_to_date(now, days=-1, minutes=-number),
				priority="Critical",
			)
		source = add_source()

		listed = [title for start in range(0, 105, 7) for title in self.titles(self.reader, source, start, 7)]

		self.assertEqual(len(listed), 103)
		self.assertEqual(len(set(listed)), 103)
		self.assertEqual(listed[:2], ["Recent 000", "Recent 001"])
		self.assertEqual(
			listed[98:],
			["Recent 098", "Recent 099", "Old, immediate 0", "Old, immediate 1", "Old, immediate 2"],
		)

	def test_filter_placeholders_select_the_rows_of_the_session_user(self):
		add_request("Mine, due today", assigned_to=self.reader, due_date=today())
		add_request("Mine, due yesterday", assigned_to=self.reader, due_date=add_days(today(), -1))
		add_request("Theirs, due today", assigned_to=self.other_reader, due_date=today())
		source = add_source(
			filters_json=json.dumps(
				[["status", "=", "Open"], ["assigned_to", "=", "{user}"], ["due_date", ">=", "{today}"]]
			)
		)

		self.assertEqual(self.titles(self.reader, source), ["Mine, due today"])
		self.assertEqual(self.titles(self.other_reader, source), ["Theirs, due today"])
		self.assertEqual(self.counts(self.other_reader, source)["count"], 1)

	def test_rows_a_role_permission_limits_to_their_owner_are_hidden_from_others(self):
		own_reader = make_user("own.reader@example.com", [OWN_READER])
		add_request("Own request", owner=own_reader)
		add_request("Someone else's request")
		source = add_source()

		self.assertEqual(self.titles(own_reader, source), ["Own request"])
		self.assertEqual(self.counts(own_reader, source)["count"], 1)
		self.assertCountEqual(self.titles(self.reader, source), ["Own request", "Someone else's request"])

	def test_a_user_without_read_permission_gets_an_error_and_nothing_else(self):
		outsider = make_user("outsider@example.com", [make_desk_role("_Test Attention Outsider")])
		add_request("Request")
		source = add_source()
		frappe.set_user(outsider)

		with self.assertLogs(logger(), "ERROR"):
			counts = runner.run_count(source, outsider)
			items = runner.run_items(source, outsider, 0, 10)

		self.assertEqual((counts["state"], counts["count"]), ("error", 0))
		self.assertEqual(items, {"state": "error", "items": []})

	def test_rows_a_user_permission_does_not_allow_are_hidden(self):
		restricted = make_user("restricted.reader@example.com", [READER])
		allowed = add_request("Allowed request")
		add_request("Other request")
		add_user_permission(REQUEST, allowed, restricted)
		source = add_source()

		self.assertEqual(self.titles(restricted, source), ["Allowed request"])
		self.assertEqual(self.counts(restricted, source)["count"], 1)
		self.assertCountEqual(self.titles(self.reader, source), ["Allowed request", "Other request"])

	def test_rows_permission_query_conditions_exclude_are_hidden(self):
		add_request("Public request")
		add_request("Confidential request", confidential=1, assigned_to=self.reader)
		source = add_source()

		with permission_query_conditions(REQUEST, f"{__name__}.confidential_requests_condition"):
			self.assertCountEqual(
				self.titles(self.reader, source), ["Public request", "Confidential request"]
			)
			self.assertEqual(self.titles(self.other_reader, source), ["Public request"])
			self.assertEqual(self.counts(self.other_reader, source)["count"], 1)

	def test_a_query_slower_than_its_budget_is_stopped_and_the_timeout_restored(self):
		add_request("Request")
		source = add_source()
		timeout_before = frappe.db.sql("select @@session.max_statement_time")[0][0]
		frappe.set_user(self.reader)

		with (
			permission_query_conditions(REQUEST, f"{__name__}.slow_condition"),
			patch.object(doctype_query, "QUERY_TIMEOUT_SECONDS", 0.2),
			self.assertLogs(logger(), "ERROR") as logs,
		):
			started = time.monotonic()
			result = runner.run_count(source, self.reader)
			elapsed = time.monotonic() - started

		self.assertEqual(result["state"], "error")
		self.assertLess(elapsed, 0.9, "the one-second sleep must have been interrupted")
		self.assertIn(f"source {KEY} failed for {self.reader}", logs.output[0])
		self.assertEqual(frappe.db.sql("select @@session.max_statement_time")[0][0], timeout_before)
		self.assertEqual(self.titles(self.reader, source), ["Request"])
