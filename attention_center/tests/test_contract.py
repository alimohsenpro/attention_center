from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_system_timezone, getdate, now_datetime

from attention_center.engine.contract import (
	ContractError,
	normalize_count,
	normalize_item,
	normalize_items,
	validate_source_def,
)

QUERY_DEF = {
	"key": "test_app.open_requests",
	"contract_version": 1,
	"label": "Open Requests",
	"kind": "action",
	"type": "doctype_query",
	"doctype": "ToDo",
	"filters": [["status", "=", "Open"], ["allocated_to", "=", "{user}"]],
	"fields": {
		"title": "description",
		"from": "assigned_by",
		"date": "creation",
		"priority": "priority",
		"due": "date",
		"status": "status",
	},
	"priority_map": {"High": "urgent"},
	"recipient_fields": ["allocated_to"],
	"icon": "inbox",
	"list_route": "/app/todo?status=Open",
}
PYTHON_DEF = {
	"key": "test_app.unit_inbox",
	"contract_version": 1,
	"label": "Unit Inbox",
	"kind": "info",
	"type": "python",
	"get_count": "test_app.attention.unit_inbox_count",
	"get_items": "test_app.attention.unit_inbox_items",
	"get_recipients": "test_app.attention.unit_inbox_recipients",
	"watch_doctypes": ["ToDo", "Note"],
	"list_route": "/app/note",
}
ITEM = {"id": "REQ-1", "title": "Review the plan", "route": "/app/todo/REQ-1"}


def without(mapping: dict, *keys: str) -> dict:
	return {key: value for key, value in mapping.items() if key not in keys}


def logger():
	return frappe.logger("attention_center")


class TestSourceDefinition(FrappeTestCase):
	def test_valid_declarative_and_python_entries_pass(self):
		cases = {
			"declarative": QUERY_DEF,
			"declarative with required keys only": {
				**without(QUERY_DEF, "filters", "priority_map", "recipient_fields", "icon", "list_route"),
				"fields": {"title": "description", "date": "creation"},
			},
			"python": PYTHON_DEF,
			"python with required keys only": without(
				PYTHON_DEF, "get_recipients", "watch_doctypes", "list_route"
			),
			"optional keys set to None": {**QUERY_DEF, "filters": None, "icon": None, "list_route": None},
			"declarative with route fields": {
				**QUERY_DEF,
				"route_fields": {
					"route": "description",
					"doctype": "reference_type",
					"name": "reference_name",
				},
			},
		}
		for case, definition in cases.items():
			with self.subTest(case):
				self.assertIsNone(validate_source_def(definition))

	def test_each_broken_rule_is_rejected_with_its_reason(self):
		cases = {
			"not a dict": (["test_app.open_requests"], "not a dict"),
			"no contract_version": (without(QUERY_DEF, "contract_version"), "contract_version None"),
			"unsupported contract_version": ({**QUERY_DEF, "contract_version": 2}, "contract_version 2"),
			"contract_version as text": ({**QUERY_DEF, "contract_version": "1"}, "contract_version '1'"),
			"contract_version as boolean": ({**QUERY_DEF, "contract_version": True}, "contract_version True"),
			"no key": (without(QUERY_DEF, "key"), "app.identifier"),
			"key without an app part": ({**QUERY_DEF, "key": "open_requests"}, "app.identifier"),
			"key with capitals": ({**QUERY_DEF, "key": "Test_App.requests"}, "app.identifier"),
			"no type": (without(QUERY_DEF, "type"), "type must be"),
			"unknown type": ({**QUERY_DEF, "type": "sql"}, "type must be"),
			"misspelt key": ({**QUERY_DEF, "filter": [["status", "=", "Open"]]}, "unknown keys .*: filter$"),
			"python key in a declarative entry": (
				{**QUERY_DEF, "get_count": "test_app.attention.count"},
				"unknown keys for type doctype_query: get_count",
			),
			"declarative key in a python entry": (
				{**PYTHON_DEF, "doctype": "ToDo"},
				"unknown keys for type python: doctype",
			),
			"no label": (without(QUERY_DEF, "label"), "label"),
			"blank label": ({**QUERY_DEF, "label": "  "}, "label"),
			"unknown kind": ({**QUERY_DEF, "kind": "urgent"}, "kind"),
			"kind as a desk option": ({**QUERY_DEF, "kind": "Action"}, "kind"),
			"icon not text": ({**QUERY_DEF, "icon": 3}, "icon"),
			"list_route outside the desk": (
				{**QUERY_DEF, "list_route": "https://example.com/app/todo"},
				"list_route",
			),
			"no doctype": (without(QUERY_DEF, "doctype"), "doctype"),
			"no fields": (without(QUERY_DEF, "fields"), "fields must map"),
			"fields not a dict": ({**QUERY_DEF, "fields": ["description", "creation"]}, "fields must map"),
			"unknown field role": (
				{**QUERY_DEF, "fields": {**QUERY_DEF["fields"], "subject": "description"}},
				"unknown fields roles: subject",
			),
			"no title field": (
				{**QUERY_DEF, "fields": without(QUERY_DEF["fields"], "title")},
				"must map title",
			),
			"no date field": ({**QUERY_DEF, "fields": without(QUERY_DEF["fields"], "date")}, "must map date"),
			"fieldname not text": ({**QUERY_DEF, "fields": {**QUERY_DEF["fields"], "due": 1}}, "fieldname"),
			"filters not a list": ({**QUERY_DEF, "filters": {"status": "Open"}}, "filters"),
			"date value in a filter": (
				{**QUERY_DEF, "filters": [["date", ">", date(2026, 1, 1)]]},
				"filters must hold only JSON values",
			),
			"set of values in an in filter": (
				{**QUERY_DEF, "filters": [["status", "in", {"Open", "Closed"}]]},
				"filters must hold only JSON values",
			),
			"priority_map with a tuple key": (
				{**QUERY_DEF, "priority_map": {("High",): "urgent"}},
				"priority_map must hold only JSON values",
			),
			"priority_map not a dict": ({**QUERY_DEF, "priority_map": [["High", "urgent"]]}, "priority_map"),
			"recipient_fields as text": (
				{**QUERY_DEF, "recipient_fields": "allocated_to"},
				"recipient_fields",
			),
			"route_fields not a dict": (
				{**QUERY_DEF, "route_fields": ["reference_type", "reference_name"]},
				"route_fields must map route, doctype, name",
			),
			"unknown route field role": (
				{**QUERY_DEF, "route_fields": {"doctype": "reference_type", "docname": "reference_name"}},
				"route_fields must map",
			),
			"route fieldname not text": (
				{**QUERY_DEF, "route_fields": {"route": 1}},
				"route_fields must map",
			),
			"route_fields in a python entry": (
				{**PYTHON_DEF, "route_fields": {"route": "link"}},
				"unknown keys for type python: route_fields",
			),
			"no get_count": (without(PYTHON_DEF, "get_count"), "get_count"),
			"no get_items": (without(PYTHON_DEF, "get_items"), "get_items"),
			"get_items not a dotted path": ({**PYTHON_DEF, "get_items": "unit inbox items"}, "get_items"),
			"get_count as a function object": ({**PYTHON_DEF, "get_count": len}, "get_count"),
			"get_recipients not a dotted path": (
				{**PYTHON_DEF, "get_recipients": "recipients"},
				"get_recipients",
			),
			"watch_doctypes as text": ({**PYTHON_DEF, "watch_doctypes": "ToDo"}, "watch_doctypes"),
		}
		for case, (definition, reason) in cases.items():
			with self.subTest(case):
				with self.assertRaisesRegex(ContractError, reason):
					validate_source_def(definition)


class TestItemNormalisation(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_complete_item_keeps_only_the_contract_fields(self):
		due = add_days(getdate(), 3)
		item = normalize_item(
			{
				**ITEM,
				"type_label": "Request",
				"from_label": "Front Desk",
				"date": datetime(2026, 11, 9, 10, 30, 15, 250),
				"priority": "urgent",
				"due": due,
				"status_label": "Open",
				"status_color": "blue",
				"body": "not part of the contract",
			}
		)

		self.assertEqual(
			item,
			{
				"id": "REQ-1",
				"title": "Review the plan",
				"route": "/app/todo/REQ-1",
				"type_label": "Request",
				"from_label": "Front Desk",
				"date": "2026-11-09T10:30:15",
				"priority": "urgent",
				"due": due.isoformat(),
				"overdue": False,
				"status_label": "Open",
				"status_color": "blue",
			},
		)

	def test_minimal_item_gets_the_defaults(self):
		item = normalize_item({**ITEM, "id": 42})

		self.assertEqual((item["id"], item["priority"], item["status_color"]), ("42", "normal", "gray"))
		self.assertEqual(
			[item[key] for key in ("type_label", "from_label", "date", "due", "status_label")], [None] * 5
		)
		self.assertFalse(item["overdue"])

	def test_items_without_a_valid_id_title_or_route_are_dropped(self):
		cases = {
			"not a dict": "REQ-1",
			"no id": without(ITEM, "id"),
			"blank id": {**ITEM, "id": " "},
			"boolean id": {**ITEM, "id": True},
			"no title": without(ITEM, "title"),
			"title not text": {**ITEM, "title": 5},
			"title made only of markup": {**ITEM, "title": "<p> </p>"},
			"no route": without(ITEM, "route"),
			"route outside the desk": {**ITEM, "route": "https://example.com/app/todo/REQ-1"},
			"script route": {**ITEM, "route": "javascript:alert(1)"},
			"reference without a name": {**without(ITEM, "route"), "reference_doctype": "ToDo"},
		}
		for case, raw in cases.items():
			with self.subTest(case):
				self.assertIsNone(normalize_item(raw))

	def test_title_is_plain_text_of_at_most_200_characters(self):
		marked_up = normalize_item({**ITEM, "title": "<p>Tom &amp; Jerry</p>\n<b>weekly</b>  report"})
		long = normalize_item({**ITEM, "title": "a" * 250})

		self.assertEqual(marked_up["title"], "Tom & Jerry weekly report")
		self.assertEqual(long["title"], "a" * 200)

	def test_route_is_built_from_the_reference_when_no_desk_route_is_given(self):
		reference = {"reference_doctype": "ToDo", "reference_name": "TD 0001"}
		for case, raw in {
			"no route": {**without(ITEM, "route"), **reference},
			"route outside the desk": {**ITEM, "route": "/files/plan.pdf", **reference},
		}.items():
			with self.subTest(case):
				self.assertEqual(normalize_item(raw)["route"], "/app/todo/TD%200001")

	def test_dates_become_iso_text_and_overdue_follows_the_due_date(self):
		now = now_datetime().replace(microsecond=0)
		today = getdate()
		system_zone = ZoneInfo(get_system_timezone())
		utc_noon = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
		cases = {
			"date before today": (add_days(today, -1), add_days(today, -1).isoformat(), True),
			"today": (today, today.isoformat(), False),
			"datetime that has passed": (
				now - timedelta(hours=1),
				(now - timedelta(hours=1)).isoformat(),
				True,
			),
			"datetime still ahead": (now + timedelta(hours=1), (now + timedelta(hours=1)).isoformat(), False),
			"ISO date text": (add_days(today, -1).isoformat(), add_days(today, -1).isoformat(), True),
			"ISO datetime text": ("2030-05-06 07:08:09", "2030-05-06T07:08:09", False),
			"aware datetime": (
				utc_noon,
				utc_noon.astimezone(system_zone).replace(tzinfo=None).isoformat(),
				True,
			),
			"text that is not a date": ("next week", None, False),
			"number": (20260101, None, False),
		}
		for case, (due, expected_due, expected_overdue) in cases.items():
			with self.subTest(case):
				item = normalize_item({**ITEM, "due": due, "date": due})
				self.assertEqual((item["due"], item["date"]), (expected_due, expected_due))
				self.assertEqual(item["overdue"], expected_overdue)

	def test_invalid_optional_values_fall_back_to_their_defaults(self):
		item = normalize_item(
			{**ITEM, "priority": "high", "status_color": "purple", "type_label": 5, "status_label": ["Open"]}
		)

		self.assertEqual((item["priority"], item["status_color"]), ("normal", "gray"))
		self.assertEqual((item["type_label"], item["status_label"]), (None, None))

	def test_from_user_is_shown_by_full_name_unless_a_from_label_is_given(self):
		sender = frappe.get_doc(
			{
				"doctype": "User",
				"email": "item.sender@example.com",
				"first_name": "Sample",
				"last_name": "Sender",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

		by_user = normalize_item({**ITEM, "from_user": sender.name})
		by_label = normalize_item({**ITEM, "from_user": sender.name, "from_label": "Front Desk"})

		self.assertEqual(by_user["from_label"], "Sample Sender")
		self.assertEqual(by_label["from_label"], "Front Desk")


class TestItemList(FrappeTestCase):
	def test_invalid_and_repeated_items_are_dropped_with_one_warning_without_content(self):
		items = [
			ITEM,
			{"id": "REQ-2", "title": "Confidential salary review"},
			{**ITEM, "title": "Same id again"},
			"not an item",
			{"id": "REQ-3", "title": "Sign the order", "route": "/app/todo/REQ-3"},
		]
		with self.assertLogs(logger(), "WARNING") as logs:
			normalized = normalize_items("test_app.unit_inbox", items)

		self.assertEqual([item["id"] for item in normalized], ["REQ-1", "REQ-3"])
		self.assertEqual(len(logs.output), 1)
		self.assertIn("test_app.unit_inbox", logs.output[0])
		self.assertIn("dropped 3 of 5", logs.output[0])
		for text in ("Confidential", "Same id", "not an item", "REQ-"):
			self.assertNotIn(text, logs.output[0])

	def test_valid_items_are_kept_in_order_without_logging(self):
		items = [{**ITEM, "id": str(number)} for number in (3, 1, 2)]
		with self.assertNoLogs(logger(), "WARNING"):
			normalized = normalize_items("test_app.unit_inbox", items)

		self.assertEqual([item["id"] for item in normalized], ["3", "1", "2"])

	def test_a_result_that_is_not_a_list_breaks_the_contract(self):
		for result in (None, ITEM, "REQ-1", (ITEM,)):
			with self.subTest(result=result):
				with self.assertRaisesRegex(ContractError, "test_app.unit_inbox"):
					normalize_items("test_app.unit_inbox", result)


class TestCountNormalisation(FrappeTestCase):
	def test_a_whole_number_or_a_dict_becomes_capped_counts(self):
		nothing = {"urgent": 0, "immediate": 0, "overdue": 0, "new_since": 0, "latest": None}
		cases = {
			"zero": (0, {"count": 0, "capped": False, **nothing}),
			"99": (99, {"count": 99, "capped": False, **nothing}),
			"100": (100, {"count": 99, "capped": True, **nothing}),
			"every counter": (
				{
					"count": 7,
					"urgent": 1,
					"immediate": 2,
					"overdue": 3,
					"new_since": 4,
					"latest": datetime(2026, 11, 9, 10, 30),
				},
				{
					"count": 7,
					"capped": False,
					"urgent": 1,
					"immediate": 2,
					"overdue": 3,
					"new_since": 4,
					"latest": "2026-11-09T10:30:00",
				},
			),
			"counters above the cap": (
				{"count": 250, "urgent": 120, "immediate": 100, "overdue": 99, "new_since": 250},
				{
					"count": 99,
					"capped": True,
					"urgent": 99,
					"immediate": 99,
					"overdue": 99,
					"new_since": 99,
					"latest": None,
				},
			),
			"empty counters": (
				{"count": 3, "urgent": None, "latest": None},
				{"count": 3, "capped": False, **nothing},
			),
			"latest as a date": (
				{"count": 1, "latest": date(2026, 11, 9)},
				{"count": 1, "capped": False, **nothing, "latest": "2026-11-09"},
			),
			"latest as ISO text": (
				{"count": 1, "latest": "2026-11-09 10:30:00"},
				{"count": 1, "capped": False, **nothing, "latest": "2026-11-09T10:30:00"},
			),
			"other keys": ({"count": 2, "titles": ["Plan"]}, {"count": 2, "capped": False, **nothing}),
		}
		for case, (result, expected) in cases.items():
			with self.subTest(case):
				self.assertEqual(normalize_count(result), expected)

	def test_a_count_of_the_wrong_shape_breaks_the_contract(self):
		cases = {
			"None": (None, "the count must be"),
			"text": ("3", "the count must be"),
			"negative": (-1, "the count must be"),
			"boolean": (True, "the count must be"),
			"fraction": (2.5, "the count must be"),
			"list": ([1, 2], "the count must be"),
			"dict without count": ({"urgent": 1}, "the count must be"),
			"count as text": ({"count": "3"}, "the count must be"),
			"negative counter": ({"count": 3, "overdue": -1}, "overdue must be"),
			"counters as fractions": (
				{"count": 3, "urgent": 1.5, "new_since": 0.5},
				"urgent, new_since must be",
			),
			"latest not a date": ({"count": 3, "latest": "yesterday"}, "latest must be"),
			"latest as a number": ({"count": 3, "latest": 20261109}, "latest must be"),
		}
		for case, (result, reason) in cases.items():
			with self.subTest(case):
				with self.assertRaisesRegex(ContractError, reason):
					normalize_count(result)
