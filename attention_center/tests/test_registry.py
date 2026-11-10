import time
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from attention_center.engine import registry
from attention_center.install import after_install, after_migrate
from attention_center.tests.utils import make_desk_role, make_user

SOURCE = "Attention Source"
# Installed apps standing in for consumer apps; frappe comes first in the installed order.
FIRST_APP = "frappe"
SECOND_APP = "attention_center"

TODOS = {
	"key": "test_app.open_todos",
	"contract_version": 1,
	"label": "Open ToDos",
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
	"recipient_fields": ["allocated_to", "assigned_by"],
	"icon": "check",
	"list_route": "/app/todo?status=Open",
}
INBOX = {
	"key": "test_app.unit_inbox",
	"contract_version": 1,
	"label": "Unit Inbox",
	"kind": "info",
	"type": "python",
	"get_count": "test_app.attention.unit_inbox_count",
	"get_items": "test_app.attention.unit_inbox_items",
	"get_recipients": "test_app.attention.unit_inbox_recipients",
	"watch_doctypes": ["ToDo", "Note"],
}


@contextmanager
def hook_sources(entries_by_app: dict[str, list]):
	real_get_hooks = frappe.get_hooks

	def get_hooks(hook=None, default="_KEEP_DEFAULT_LIST", app_name=None):
		if hook != "attention_sources":
			return real_get_hooks(hook, default, app_name)
		if app_name:
			return list(entries_by_app.get(app_name, []))
		return [entry for entries in entries_by_app.values() for entry in entries]

	with patch("frappe.get_hooks", side_effect=get_hooks):
		yield


def sync(entries_by_app: dict[str, list]) -> None:
	with hook_sources(entries_by_app):
		registry.sync_sources()


def logger():
	return frappe.logger("attention_center")


def source_rows(*keys: str) -> list[dict]:
	return frappe.get_all(SOURCE, filters={"name": ("in", keys)}, fields=["*"], order_by="name")


def make_user_group(name: str, members: list[str]) -> str:
	frappe.get_doc(
		{"doctype": "User Group", "name": name, "user_group_members": [{"user": user} for user in members]}
	).insert(ignore_permissions=True)
	return name


class RegistryTestCase(FrappeTestCase):
	def setUp(self):
		# The sources this app declares were synced at install; these tests declare their own.
		frappe.db.delete(SOURCE, {"is_system": 1})
		registry.clear_visibility_cache()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		registry.clear_visibility_cache()


class TestLoadHookSources(RegistryTestCase):
	def test_valid_entries_of_every_app_are_loaded_with_their_app(self):
		with hook_sources({FIRST_APP: [TODOS], SECOND_APP: [INBOX]}):
			sources = registry.load_hook_sources()

		self.assertEqual(
			{source["key"]: source["app"] for source in sources},
			{
				TODOS["key"]: FIRST_APP,
				INBOX["key"]: SECOND_APP,
			},
		)
		self.assertEqual(sources[0]["filters"], TODOS["filters"])

	def test_rejected_entries_are_logged_once_each_and_do_not_stop_the_others(self):
		entries = [
			{**TODOS, "contract_version": 2},
			{**INBOX, "key": "unit_inbox"},
			TODOS,
			{key: value for key, value in INBOX.items() if key != "get_count"},
			"test_app.loose_string",
		]
		with hook_sources({SECOND_APP: entries}), self.assertLogs(logger(), "ERROR") as logs:
			sources = registry.load_hook_sources()

		self.assertEqual([source["key"] for source in sources], [TODOS["key"]])
		self.assertEqual(len(logs.output), 4)
		for position, reason in zip(
			(1, 2, 4, 5), ("contract_version 2", "app.identifier", "get_count", "not a dict"), strict=True
		):
			with self.subTest(position=position):
				self.assertRegex(
					"\n".join(logs.output),
					f"{SECOND_APP}: attention_sources entry {position} skipped: .*{reason}",
				)

	def test_a_duplicate_key_is_skipped_and_the_first_declaration_kept(self):
		with (
			hook_sources(
				{FIRST_APP: [TODOS], SECOND_APP: [{**TODOS, "label": "Copied ToDos"}, INBOX, INBOX]}
			),
			self.assertLogs(logger(), "ERROR") as logs,
		):
			sources = registry.load_hook_sources()

		self.assertEqual(
			[(source["key"], source["label"], source["app"]) for source in sources],
			[(TODOS["key"], "Open ToDos", FIRST_APP), (INBOX["key"], "Unit Inbox", SECOND_APP)],
		)
		self.assertEqual(len(logs.output), 2)
		self.assertIn(
			f"entry 1 skipped: key {TODOS['key']} is already declared by {FIRST_APP}", logs.output[0]
		)
		self.assertIn(
			f"entry 3 skipped: key {INBOX['key']} is already declared by {SECOND_APP}", logs.output[1]
		)


class TestSyncSources(RegistryTestCase):
	def test_hook_entries_become_system_sources(self):
		sync({SECOND_APP: [TODOS, INBOX]})

		self.assertDocumentEqual(
			{
				"label": "Open ToDos",
				"kind": "Action",
				"source_type": "DocType Query",
				"enabled": 1,
				"is_system": 1,
				"app": SECOND_APP,
				"icon": "check",
				"list_route": "/app/todo?status=Open",
				"reference_doctype": "ToDo",
				"filters_json": '[["status", "=", "Open"], ["allocated_to", "=", "{user}"]]',
				"priority_map_json": '{"High": "urgent"}',
				"recipient_fields": "allocated_to, assigned_by",
				"title_field": "description",
				"from_field": "assigned_by",
				"date_field": "creation",
				"priority_field": "priority",
				"due_field": "date",
				"status_field": "status",
				"get_count": None,
			},
			frappe.get_doc(SOURCE, TODOS["key"]),
		)
		self.assertDocumentEqual(
			{
				"label": "Unit Inbox",
				"kind": "Info",
				"source_type": "Python",
				"enabled": 1,
				"is_system": 1,
				"get_count": INBOX["get_count"],
				"get_items": INBOX["get_items"],
				"get_recipients": INBOX["get_recipients"],
				"watch_doctypes": "ToDo, Note",
				"reference_doctype": None,
				"filters_json": None,
			},
			frappe.get_doc(SOURCE, INBOX["key"]),
		)

	def test_sync_is_idempotent(self):
		sync({SECOND_APP: [TODOS, INBOX]})
		first = source_rows(TODOS["key"], INBOX["key"])

		sync({SECOND_APP: [TODOS, INBOX]})

		self.assertEqual(len(first), 2)
		self.assertEqual(source_rows(TODOS["key"], INBOX["key"]), first)
		self.assertEqual(frappe.db.count(SOURCE, {"name": ("in", (TODOS["key"], INBOX["key"]))}), 2)

	def test_admin_changes_survive_a_sync_that_updates_the_definition(self):
		role = make_desk_role("_Test Attention Reader")
		group = make_user_group("_Test Attention Team", [make_user("team.member@example.com", [role])])
		sync({SECOND_APP: [TODOS]})
		doc = frappe.get_doc(SOURCE, TODOS["key"])
		doc.update({"label": "Team ToDos", "enabled": 0, "sort_order": 7})
		doc.append("roles", {"role": role})
		doc.append("user_groups", {"user_group": group})
		doc.save()

		sync(
			{
				SECOND_APP: [
					{
						**TODOS,
						"label": "Open Tasks",
						"filters": [["status", "=", "Open"]],
						"list_route": "/app/todo",
					}
				]
			}
		)

		doc.reload()
		self.assertEqual((doc.label, doc.enabled, doc.sort_order), ("Team ToDos", 0, 7))
		self.assertEqual([row.role for row in doc.roles], [role])
		self.assertEqual([row.user_group for row in doc.user_groups], [group])
		self.assertEqual((doc.filters_json, doc.list_route), ('[["status", "=", "Open"]]', "/app/todo"))

	def test_the_label_follows_the_hooks_until_an_admin_changes_it(self):
		sync({SECOND_APP: [TODOS]})
		sync({SECOND_APP: [{**TODOS, "label": "Open Tasks"}]})
		self.assertEqual(frappe.db.get_value(SOURCE, TODOS["key"], "label"), "Open Tasks")

		doc = frappe.get_doc(SOURCE, TODOS["key"])
		doc.label = "Team Tasks"
		doc.save()
		sync({SECOND_APP: [{**TODOS, "label": "My Tasks"}]})
		self.assertEqual(frappe.db.get_value(SOURCE, TODOS["key"], "label"), "Team Tasks")

	def test_a_source_no_app_declares_any_more_is_disabled_but_kept(self):
		sync({SECOND_APP: [TODOS, INBOX]})
		self.assertIn(INBOX["key"], [source.key for source in registry.get_visible_sources("Administrator")])

		with self.assertLogs(logger(), "WARNING") as logs:
			sync({SECOND_APP: [TODOS]})

		self.assertEqual(
			frappe.db.get_value(SOURCE, INBOX["key"], ["enabled", "is_system", "get_count"]),
			(0, 1, INBOX["get_count"]),
		)
		self.assertEqual(frappe.db.get_value(SOURCE, TODOS["key"], "enabled"), 1)
		self.assertEqual(len(logs.output), 1)
		self.assertIn(f"system source {INBOX['key']} disabled", logs.output[0])
		self.assertNotIn(
			INBOX["key"], [source.key for source in registry.get_visible_sources("Administrator")]
		)

		sync({})
		self.assertEqual(frappe.db.get_value(SOURCE, TODOS["key"], "enabled"), 0)

		sync({SECOND_APP: [TODOS, INBOX]})
		self.assertEqual(frappe.db.get_value(SOURCE, INBOX["key"], "enabled"), 0)

	def test_an_entry_the_source_form_rejects_is_skipped_and_logged(self):
		entries = [
			{**TODOS, "doctype": "No Such DocType"},
			{**TODOS, "key": "test_app.bad_field", "fields": {"title": "no_such_field", "date": "creation"}},
			{**TODOS, "key": "test_app.bad_filter", "filters": [["status", "between", ["Open", "Closed"]]]},
			{**TODOS, "key": "test_app.bad_priority", "priority_map": {"High": "critical"}},
			INBOX,
		]
		with self.assertLogs(logger(), "ERROR") as logs:
			sync({SECOND_APP: entries})

		self.assertEqual(
			[
				row.name
				for row in source_rows(
					TODOS["key"],
					"test_app.bad_field",
					"test_app.bad_filter",
					"test_app.bad_priority",
					INBOX["key"],
				)
			],
			[INBOX["key"]],
		)
		self.assertEqual(len(logs.output), 4)
		for key in (TODOS["key"], "test_app.bad_field", "test_app.bad_filter", "test_app.bad_priority"):
			with self.subTest(key=key):
				self.assertTrue(any(f"hook source {key} skipped" in line for line in logs.output))

	def test_an_entry_holding_values_json_cannot_store_is_skipped_and_migrate_goes_on(self):
		entries = [
			{**TODOS, "filters": [["date", ">", date(2026, 1, 1)]]},
			{**TODOS, "key": "test_app.grouped", "filters": [["status", "in", {"Open", "Closed"}]]},
			INBOX,
		]
		with hook_sources({SECOND_APP: entries}), self.assertLogs(logger(), "ERROR") as logs:
			after_migrate()

		self.assertEqual(
			[row.name for row in source_rows(TODOS["key"], "test_app.grouped", INBOX["key"])], [INBOX["key"]]
		)
		self.assertEqual(len(logs.output), 2)
		for position in (1, 2):
			with self.subTest(position=position):
				self.assertIn(
					f"entry {position} skipped: filters must hold only JSON values", "\n".join(logs.output)
				)

	def test_a_system_source_whose_new_definition_is_rejected_is_disabled(self):
		sync({SECOND_APP: [TODOS]})

		with self.assertLogs(logger(), "WARNING"):
			sync({SECOND_APP: [{**TODOS, "fields": {"title": "no_such_field", "date": "creation"}}]})

		self.assertEqual(
			frappe.db.get_value(SOURCE, TODOS["key"], ["enabled", "title_field"]), (0, "description")
		)

	def test_a_desk_source_using_the_same_key_is_left_alone(self):
		frappe.get_doc(
			{
				"doctype": SOURCE,
				"key": TODOS["key"],
				"label": "Desk ToDos",
				"kind": "Action",
				"source_type": "DocType Query",
				"reference_doctype": "ToDo",
				"title_field": "name",
				"date_field": "modified",
			}
		).insert()

		with self.assertLogs(logger(), "ERROR") as logs:
			sync({SECOND_APP: [TODOS]})

		self.assertEqual(
			frappe.db.get_value(
				SOURCE, TODOS["key"], ["is_system", "enabled", "label", "title_field", "app"]
			),
			(0, 1, "Desk ToDos", "name", None),
		)
		self.assertIn("a source created in the desk uses this key", logs.output[0])

	def test_install_and_migrate_sync_the_hook_sources(self):
		with hook_sources({SECOND_APP: [TODOS]}):
			after_install()
		self.assertEqual(frappe.db.get_value(SOURCE, TODOS["key"], ["is_system", "enabled"]), (1, 1))

		with hook_sources({}), self.assertLogs(logger(), "WARNING"):
			after_migrate()
		self.assertEqual(frappe.db.get_value(SOURCE, TODOS["key"], "enabled"), 0)


class TestVisibleSources(RegistryTestCase):
	def setUp(self):
		super().setUp()
		self.reader_role = make_desk_role("_Test Attention Reader")
		self.other_role = make_desk_role("_Test Attention Other")
		self.first_user = make_user("first.user@example.com", [self.reader_role])
		self.second_user = make_user("second.user@example.com", [self.other_role])

	def add_source(self, key: str, roles=(), user_groups=(), **values) -> str:
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
				"roles": [{"role": role} for role in roles],
				"user_groups": [{"user_group": group} for group in user_groups],
				**values,
			}
		).insert()
		return key

	def visible(self, user: str) -> list[str]:
		return [source.key for source in registry.get_visible_sources(user)]

	def test_a_source_without_targeting_is_visible_to_every_desk_user(self):
		key = self.add_source("test_app.everyone")

		self.assertEqual(self.visible(self.first_user), [key])
		self.assertEqual(self.visible(self.second_user), [key])

	def test_role_targeting_shows_the_source_only_to_holders_of_a_listed_role(self):
		key = self.add_source("test_app.readers", roles=[self.reader_role])

		self.assertEqual(self.visible(self.first_user), [key])
		self.assertEqual(self.visible(self.second_user), [])

	def test_user_group_targeting_shows_the_source_only_to_members(self):
		group = make_user_group("_Test Attention Team", [self.second_user])
		key = self.add_source("test_app.team", user_groups=[group])

		self.assertEqual(self.visible(self.second_user), [key])
		self.assertEqual(self.visible(self.first_user), [])

	def test_roles_and_groups_together_admit_a_user_matching_either(self):
		group = make_user_group("_Test Attention Team", [self.second_user])
		third_user = make_user("third.user@example.com", [make_desk_role("_Test Attention Third")])
		key = self.add_source("test_app.mixed", roles=[self.reader_role], user_groups=[group])

		self.assertEqual(self.visible(self.first_user), [key])
		self.assertEqual(self.visible(self.second_user), [key])
		self.assertEqual(self.visible(third_user), [])

	def test_a_disabled_source_is_visible_to_nobody(self):
		self.add_source("test_app.disabled", enabled=0)

		for user in (self.first_user, self.second_user, "Administrator"):
			with self.subTest(user=user):
				self.assertEqual(self.visible(user), [])

	def test_a_declarative_source_needs_read_permission_on_its_doctype(self):
		error_logs = {"reference_doctype": "Error Log", "title_field": "method", "date_field": "creation"}
		open_key = self.add_source("test_app.error_logs", **error_logs)
		targeted_key = self.add_source("test_app.targeted_error_logs", roles=[self.reader_role], **error_logs)
		manager = make_user("source.reader@example.com", ["System Manager", self.reader_role])

		self.assertFalse(frappe.has_permission("Error Log", "read", user=self.first_user))
		self.assertEqual(self.visible(self.first_user), [])
		self.assertEqual(self.visible(self.second_user), [])
		self.assertEqual(self.visible(manager), [open_key, targeted_key])

	def test_a_python_source_is_targeted_without_a_doctype_check(self):
		with hook_sources({SECOND_APP: [INBOX]}):
			registry.sync_sources()
		doc = frappe.get_doc(SOURCE, INBOX["key"])
		doc.append("roles", {"role": self.reader_role})
		doc.save()

		self.assertEqual(self.visible(self.first_user), [INBOX["key"]])
		self.assertEqual(self.visible(self.second_user), [])

	def test_sources_come_in_sort_order_then_creation_order(self):
		self.add_source("test_app.third", sort_order=2)
		self.add_source("test_app.first", sort_order=1)
		self.add_source("test_app.second", sort_order=1)

		self.assertEqual(
			self.visible(self.first_user), ["test_app.first", "test_app.second", "test_app.third"]
		)

	def test_a_source_whose_doctype_is_gone_is_hidden_without_failing(self):
		gone = self.add_source("test_app.gone")
		kept = self.add_source("test_app.kept")
		frappe.db.set_value(SOURCE, gone, "reference_doctype", "Removed DocType")
		registry.clear_visibility_cache()

		self.assertEqual(self.visible(self.first_user), [kept])

	def test_saving_or_deleting_a_source_and_saving_the_settings_refresh_visibility_at_once(self):
		key = self.add_source("test_app.everyone")
		self.assertEqual(self.visible(self.first_user), [key])

		doc = frappe.get_doc(SOURCE, key)
		doc.append("roles", {"role": self.other_role})
		doc.save()
		self.assertEqual(self.visible(self.first_user), [])
		self.assertEqual(self.visible(self.second_user), [key])

		frappe.db.set_value(SOURCE, key, "enabled", 0)
		self.assertEqual(
			self.visible(self.second_user), [key], "a direct database write is not seen before expiry"
		)
		frappe.get_single("Attention Center Settings").save()
		self.assertEqual(self.visible(self.second_user), [])

		other = self.add_source("test_app.other")
		self.assertEqual(self.visible(self.first_user), [other])
		frappe.delete_doc(SOURCE, other)
		self.assertEqual(self.visible(self.first_user), [])

	def test_role_and_group_changes_are_seen_once_the_cached_entry_expires(self):
		group = make_user_group("_Test Attention Team", [self.first_user])
		role_key = self.add_source("test_app.readers", roles=[self.reader_role])
		group_key = self.add_source("test_app.team", user_groups=[group])
		self.assertEqual(self.visible(self.second_user), [])

		frappe.get_doc("User", self.second_user).add_roles(self.reader_role)
		team = frappe.get_doc("User Group", group)
		team.append("user_group_members", {"user": self.second_user})
		team.save()
		self.assertEqual(self.visible(self.second_user), [])

		with patch.object(registry, "time") as clock:
			clock.time.return_value = time.time() + registry.VISIBLE_TTL_SECONDS + 1
			self.assertEqual(self.visible(self.second_user), [role_key, group_key])
