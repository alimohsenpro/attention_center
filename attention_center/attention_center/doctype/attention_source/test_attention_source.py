# Copyright (c) 2026, Attention Center Contributors and Contributors
# See license.txt

import json

import frappe
from frappe.client import insert as client_insert
from frappe.client import save as client_save
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase

from attention_center.tests.utils import make_desk_role, make_user

QUERY_SOURCE = {
	"doctype": "Attention Source",
	"key": "test_app.open_todos",
	"label": "Open ToDos",
	"kind": "Action",
	"source_type": "DocType Query",
	"reference_doctype": "ToDo",
	"filters_json": json.dumps([["status", "=", "Open"], ["allocated_to", "=", "{user}"]]),
	"title_field": "description",
	"from_field": "assigned_by",
	"date_field": "creation",
	"priority_field": "priority",
	"due_field": "date",
	"status_field": "status",
	"priority_map_json": json.dumps({"High": "urgent"}),
	"recipient_fields": "allocated_to, assigned_by",
	"list_route": "/app/todo?status=Open",
}

PYTHON_SOURCE = {
	"doctype": "Attention Source",
	"key": "test_app.unit_inbox",
	"label": "Unit Inbox",
	"kind": "Action",
	"source_type": "Python",
	"is_system": 1,
	"app": "test_app",
	"get_count": "test_app.attention.unit_inbox_count",
	"get_items": "test_app.attention.unit_inbox_items",
	"get_recipients": "test_app.attention.unit_inbox_recipients",
	"watch_doctypes": "ToDo",
}

SYSTEM_QUERY_SOURCE = {**QUERY_SOURCE, "is_system": 1, "app": "test_app"}
MAPPED_FIELDS = ("title_field", "from_field", "date_field", "priority_field", "due_field", "status_field")
CALLABLE_FIELDS = ("get_count", "get_items", "get_recipients", "watch_doctypes")


def query_source(**overrides) -> Document:
	return frappe.get_doc({**QUERY_SOURCE, **overrides})


def from_hooks(definition: dict) -> Document:
	doc = frappe.get_doc(definition)
	doc.flags.from_hooks = True
	return doc


class TestAttentionSource(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def assertRejected(self, doc: Document, message: str = ""):
		with self.assertRaisesRegex(frappe.ValidationError, message):
			doc.insert()

	def test_valid_declarative_source_is_saved_under_its_key(self):
		doc = query_source().insert()

		self.assertEqual(doc.name, "test_app.open_todos")
		self.assertEqual(doc.is_system, 0)
		self.assertEqual(doc.enabled, 1)

	def test_key_must_look_like_app_dot_identifier(self):
		for key in ("test_app.open_todos", "a.b.c", "app_1.queue_2"):
			with self.subTest(key=key):
				query_source(key=key).insert()

		for key in (
			"open_todos",
			"Test_App.todos",
			"test-app.todos",
			"test_app..todos",
			"test_app.",
			".todos",
			"test app.todos",
			"test_app.todos\n",
		):
			with self.subTest(key=key):
				self.assertRejected(query_source(key=key), "app.identifier")

	def test_key_is_fixed_once_the_source_exists(self):
		# set_only_once makes the form show the key read-only; the server already keeps it equal to the name.
		self.assertEqual(frappe.get_meta("Attention Source").get_field("key").set_only_once, 1)
		doc = query_source().insert()
		doc.key = "test_app.renamed"
		doc.save()

		self.assertEqual(
			frappe.db.get_value("Attention Source", QUERY_SOURCE["key"], "key"), QUERY_SOURCE["key"]
		)
		self.assertFalse(frappe.db.exists("Attention Source", "test_app.renamed"))

	def test_reference_doctype_must_be_a_doctype_with_its_own_records(self):
		cases = {
			"missing": None,
			"unknown": "No Such DocType",
			"child table": "Has Role",
			"single": "System Settings",
		}
		for case, doctype in cases.items():
			with self.subTest(case):
				self.assertRejected(query_source(reference_doctype=doctype))

	def test_title_and_date_fields_are_required(self):
		for fieldname in ("title_field", "date_field"):
			with self.subTest(fieldname):
				self.assertRejected(query_source(**{fieldname: None}), "required")

	def test_mapped_fields_must_be_fields_of_the_doctype(self):
		layout_field = next(
			df.fieldname for df in frappe.get_meta("ToDo").fields if df.fieldtype == "Section Break"
		)
		for fieldname in MAPPED_FIELDS:
			for value in ("no_such_field", layout_field):
				with self.subTest(fieldname=fieldname, value=value):
					self.assertRejected(query_source(**{fieldname: value}), "has no field")

	def test_standard_fields_can_be_mapped(self):
		doc = query_source(
			title_field="name",
			from_field="owner",
			date_field="modified",
			due_field="creation",
			status_field="docstatus",
			recipient_fields="owner,modified_by",
		).insert()

		self.assertEqual(doc.title_field, "name")

	def test_route_fields_must_be_fields_of_the_doctype(self):
		for fieldname in ("route_field", "route_doctype_field", "route_name_field"):
			with self.subTest(fieldname):
				self.assertRejected(query_source(**{fieldname: "no_such_field"}), "has no field")

	def test_the_route_doctype_and_name_fields_are_set_together(self):
		for fieldname in ("route_doctype_field", "route_name_field"):
			with self.subTest(fieldname):
				self.assertRejected(query_source(**{fieldname: "reference_type"}), "together")

		doc = query_source(
			route_field="description", route_doctype_field="reference_type", route_name_field="reference_name"
		).insert()
		self.assertEqual(doc.route_name_field, "reference_name")

	def test_recipient_fields_must_be_fields_of_the_doctype(self):
		self.assertRejected(query_source(recipient_fields="allocated_to, no_such_field"), "has no field")

	def test_filters_accept_every_allowed_operator_and_both_placeholders(self):
		filters = [
			["status", "=", "Open"],
			["priority", "!=", "Low"],
			["modified", ">", "2026-01-01"],
			["date", "<", "{today}"],
			["date", ">=", "2026-01-01"],
			["date", "<=", "{today}"],
			["status", "in", ["Open", "Closed"]],
			["allocated_to", "not in", ["{user}"]],
			["description", "like", "%report%"],
			["reference_type", "is", "set"],
			["allocated_to", "=", "{user}"],
		]
		for index, filters_json in enumerate((json.dumps(filters), "[]", "", None)):
			with self.subTest(filters_json=filters_json):
				query_source(key=f"test_app.filters_{index}", filters_json=filters_json).insert()

	def test_malformed_filters_are_rejected(self):
		cases = {
			"not json": "[[",
			"not a list": json.dumps({"status": "Open"}),
			"condition is not a list": json.dumps(["status"]),
			"two items": json.dumps([["status", "="]]),
			"four items": json.dumps([["status", "=", "Open", "Closed"]]),
			"field is not text": json.dumps([[1, "=", "Open"]]),
			"unknown field": json.dumps([["no_such_field", "=", "Open"]]),
			"operator not allowed": json.dumps([["status", "between", ["Open", "Closed"]]]),
			"list for a single-value operator": json.dumps([["status", "=", ["Open"]]]),
			"text for in": json.dumps([["status", "in", "Open,Closed"]]),
			"text for not in": json.dumps([["allocated_to", "not in", "{user}"]]),
			"nested list for in": json.dumps([["status", "in", [["Open"]]]]),
			"object as value": json.dumps([["status", "=", {"value": "Open"}]]),
			"is without set or not set": json.dumps([["reference_type", "is", "Open"]]),
			"unknown placeholder": json.dumps([["allocated_to", "=", "{owner}"]]),
			"unknown placeholder inside a list": json.dumps(
				[["allocated_to", "in", ["{user}", "{session_user}"]]]
			),
		}
		for case, filters_json in cases.items():
			with self.subTest(case):
				self.assertRejected(query_source(filters_json=filters_json))

	def test_priority_map_maps_values_to_known_priorities(self):
		mapping = {"High": "urgent", "Medium": "immediate", "Low": "normal"}
		query_source(priority_map_json=json.dumps(mapping)).insert()

		cases = {
			"not json": "{",
			"not an object": json.dumps(["urgent"]),
			"unknown priority": json.dumps({"High": "critical"}),
			"priority is not text": json.dumps({"High": ["urgent"]}),
		}
		for case, priority_map_json in cases.items():
			with self.subTest(case):
				self.assertRejected(
					query_source(key="test_app.rejected", priority_map_json=priority_map_json)
				)

	def test_priority_map_needs_a_priority_field(self):
		self.assertRejected(query_source(priority_field=None), "Priority Field")

	def test_list_route_must_be_a_desk_route(self):
		for index, route in enumerate(("/app/todo", "", None)):
			with self.subTest(route=route):
				query_source(key=f"test_app.route_{index}", list_route=route).insert()

		for route in ("https://example.com/app/todo", "/apps/todo", "app/todo", "javascript:alert(1)"):
			with self.subTest(route=route):
				self.assertRejected(query_source(list_route=route), "/app/")

	def test_messages_name_fields_in_the_app_wording(self):
		lang = frappe.local.lang
		frappe.local.lang = "ar"
		try:
			self.assertRejected(query_source(from_field="no_such_field"), "حقل المرسِل")
		finally:
			frappe.local.lang = lang

	def test_python_source_cannot_be_created_from_the_desk(self):
		self.assertRejected(frappe.get_doc({**PYTHON_SOURCE, "is_system": 0}), "hooks")
		self.assertRejected(frappe.get_doc(PYTHON_SOURCE), "hooks")

		manager = make_user("source.manager@example.com", ["Attention Manager"])
		frappe.set_user(manager)
		with self.assertRaisesRegex(frappe.ValidationError, "hooks"):
			client_insert({**PYTHON_SOURCE, "flags": {"from_hooks": True}})

		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("Attention Source", PYTHON_SOURCE["key"]))

	def test_declarative_source_cannot_name_callables(self):
		for fieldname in CALLABLE_FIELDS:
			with self.subTest(fieldname):
				self.assertRejected(query_source(**{fieldname: "test_app.attention.something"}), "callables")

	def test_hook_sync_creates_system_sources(self):
		python_source = from_hooks(PYTHON_SOURCE).insert()
		query = from_hooks(SYSTEM_QUERY_SOURCE).insert()

		self.assertEqual((python_source.is_system, python_source.source_type), (1, "Python"))
		self.assertEqual((query.is_system, query.source_type), (1, "DocType Query"))

	def test_python_source_needs_system_origin_and_count_and_items(self):
		self.assertRejected(from_hooks({**PYTHON_SOURCE, "is_system": 0}), "hooks")
		for fieldname in ("get_count", "get_items"):
			with self.subTest(fieldname):
				self.assertRejected(from_hooks({**PYTHON_SOURCE, fieldname: None}), "needs")

	def test_system_source_accepts_admin_changes(self):
		member = make_user("group.member@example.com", [make_desk_role("_Test Attention Desk Role")])
		group = frappe.get_doc(
			{
				"doctype": "User Group",
				"name": "_Test Attention Group",
				"user_group_members": [{"user": member}],
			}
		).insert()
		from_hooks(SYSTEM_QUERY_SOURCE).insert()

		doc = frappe.get_doc("Attention Source", SYSTEM_QUERY_SOURCE["key"])
		doc.update({"label": "Team ToDos", "enabled": 0, "sort_order": 5})
		doc.append("roles", {"role": "System Manager"})
		doc.append("user_groups", {"user_group": group.name})
		doc.save()

		doc.reload()
		self.assertEqual((doc.label, doc.enabled, doc.sort_order), ("Team ToDos", 0, 5))
		self.assertEqual([row.role for row in doc.roles], ["System Manager"])
		self.assertEqual([row.user_group for row in doc.user_groups], [group.name])

	def test_system_source_rejects_definition_edits(self):
		from_hooks(SYSTEM_QUERY_SOURCE).insert()
		from_hooks(PYTHON_SOURCE).insert()
		edits = {
			SYSTEM_QUERY_SOURCE["key"]: {
				"kind": "Info",
				"source_type": "Python",
				"reference_doctype": "Note",
				"filters_json": "[]",
				"title_field": "name",
				"from_field": "owner",
				"date_field": "modified",
				"priority_field": "status",
				"due_field": "modified",
				"status_field": "priority",
				"priority_map_json": json.dumps({"Low": "normal"}),
				"recipient_fields": "owner",
				"list_route": "/app/todo",
				"icon": "bell",
				"app": "other_app",
				"hook_label": "Other ToDos",
			},
			PYTHON_SOURCE["key"]: {
				"get_count": "other_app.count",
				"get_items": "other_app.items",
				"get_recipients": "",
				"watch_doctypes": "Note",
			},
		}
		for key, changes in edits.items():
			for fieldname, value in changes.items():
				with self.subTest(key=key, fieldname=fieldname):
					doc = frappe.get_doc("Attention Source", key)
					doc.set(fieldname, value)
					with self.assertRaisesRegex(frappe.ValidationError, "declared by an app's hooks"):
						doc.save()

	def test_only_hooks_can_change_the_system_flag(self):
		from_hooks(SYSTEM_QUERY_SOURCE).insert()
		doc = frappe.get_doc("Attention Source", SYSTEM_QUERY_SOURCE["key"])
		doc.is_system = 0
		with self.assertRaisesRegex(frappe.ValidationError, "Only an app's hooks"):
			doc.save()

		query_source(key="test_app.desk_source").insert()
		doc = frappe.get_doc("Attention Source", "test_app.desk_source")
		doc.is_system = 1
		with self.assertRaisesRegex(frappe.ValidationError, "Only an app's hooks"):
			doc.save()

	def test_only_hooks_can_set_the_app(self):
		self.assertRejected(query_source(app="other_app"), "Only an app's hooks")

		doc = query_source().insert()
		doc.app = "other_app"
		with self.assertRaisesRegex(frappe.ValidationError, "Only an app's hooks"):
			doc.save()

		self.assertIsNone(frappe.db.get_value("Attention Source", doc.name, "app"))

	def test_hook_sync_can_update_a_system_definition(self):
		from_hooks(SYSTEM_QUERY_SOURCE).insert()
		doc = frappe.get_doc("Attention Source", SYSTEM_QUERY_SOURCE["key"])
		doc.filters_json = "[]"
		doc.flags.from_hooks = True
		doc.save()

		self.assertEqual(frappe.db.get_value("Attention Source", doc.name, "filters_json"), "[]")

	def test_desk_save_of_a_system_source_is_not_taken_for_a_definition_edit(self):
		from_hooks(SYSTEM_QUERY_SOURCE).insert()
		manager = make_user("source.manager@example.com", ["Attention Manager"])
		payload = frappe.get_doc("Attention Source", SYSTEM_QUERY_SOURCE["key"]).as_dict(
			convert_dates_to_str=True
		)
		self.assertIsNone(payload["icon"])
		payload.update({"label": "Team ToDos", "sort_order": 3, "icon": "", "get_count": ""})

		frappe.set_user(manager)
		saved = client_save(payload)

		self.assertEqual((saved["label"], saved["sort_order"]), ("Team ToDos", 3))

	def test_managers_manage_sources_and_other_desk_users_cannot_read_them(self):
		query_source().insert()
		manager = make_user("source.manager@example.com", ["Attention Manager"])
		system_manager = make_user("source.admin@example.com", ["System Manager"])
		desk_user = make_user("desk.user@example.com", [make_desk_role("_Test Attention Desk Role")])

		for user in (manager, system_manager):
			for ptype in ("read", "write", "create", "delete"):
				with self.subTest(user=user, ptype=ptype):
					self.assertTrue(frappe.has_permission("Attention Source", ptype, user=user))
			frappe.set_user(user)
			self.assertIn(QUERY_SOURCE["key"], frappe.get_list("Attention Source", pluck="name"))

		frappe.set_user(desk_user)
		self.assertFalse(frappe.has_permission("Attention Source", "read", user=desk_user))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("Attention Source")
