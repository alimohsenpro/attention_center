import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from attention_center.engine import realtime, recipients, registry, runner
from attention_center.tests.utils import make_desk_role, make_user

SOURCE = "Attention Source"
APPROVALS = "attention_center.approvals"
ASSIGNMENTS = "attention_center.assignments"
NOTIFICATIONS = "attention_center.notifications"
# Document content that must never reach a nudge or a log.
SECRET = "Confidential merger memo"


def count_nothing(user: str) -> int:
	return 0


def items_nothing(user: str, start: int, page_length: int) -> list[dict]:
	return []


def note_viewers(doc) -> list[str]:
	return [row.user for row in doc.seen_by]


def recipients_that_raise(doc) -> list[str]:
	frappe.throw(f"Cannot list the readers of {doc.title}")


def recipients_not_in_a_list(doc) -> str:
	return doc.owner


def add_todo(allocated_to: str, description: str = "Prepare the agenda"):
	return frappe.get_doc(
		{"doctype": "ToDo", "description": description, "allocated_to": allocated_to}
	).insert(ignore_permissions=True)


def add_note(title: str = "Agenda", viewers: tuple[str, ...] = ()):
	return frappe.get_doc(
		{"doctype": "Note", "title": title, "seen_by": [{"user": user} for user in viewers]}
	).insert(ignore_permissions=True)


def logger():
	return frappe.logger("attention_center")


def messages(logs) -> list[str]:
	return [record.getMessage() for record in logs.records]


class TestRealtime(FrappeTestCase):
	def setUp(self):
		registry.sync_sources()
		self.role = make_desk_role("_Test Attention Realtime")
		self.actor = make_user("realtime.actor@example.com", [self.role])
		self.user = make_user("realtime.user@example.com", [self.role])
		self.other_user = make_user("realtime.other@example.com", [self.role])
		self.keys = [APPROVALS, ASSIGNMENTS, NOTIFICATIONS]
		publish = patch("frappe.publish_realtime")
		self.publish = publish.start()
		self.addCleanup(publish.stop)
		frappe.set_user(self.actor)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		registry.clear_visibility_cache()
		for key in self.keys:
			frappe.cache.delete_value(runner.COUNT_CACHE.format(key))

	def sent(self) -> list[tuple[str | None, dict]]:
		"""(user, message) of every nudge published so far; the user is None for a broadcast."""
		return [
			(call.kwargs.get("user"), call.args[1])
			for call in self.publish.call_args_list
			if call.args[:1] == (realtime.EVENT,)
		]

	def commit(self) -> list[tuple[str | None, dict]]:
		"""Run what Frappe runs once the transaction commits, and return the nudges it published."""
		self.publish.reset_mock()
		frappe.db.after_commit.run()
		return self.sent()

	def nudge(self, *keys: str) -> dict:
		return {"sources": list(keys), "actor": self.actor}

	def add_source(self, key: str, **values) -> str:
		"""A source as the hook sync or an Attention Manager would create it."""
		self.keys.append(key)
		frappe.set_user("Administrator")
		try:
			doc = frappe.get_doc({"doctype": SOURCE, "key": key, "label": key, "kind": "Action", **values})
			doc.flags.from_hooks = values.get("source_type") == "Python"
			doc.insert()
		finally:
			frappe.set_user(self.actor)
		return key

	def add_note_source(self, key: str, **values) -> str:
		return self.add_source(
			key,
			source_type="DocType Query",
			reference_doctype="Note",
			title_field="title",
			date_field="creation",
			**values,
		)

	def add_python_source(self, key: str, **values) -> str:
		return self.add_source(
			key,
			source_type="Python",
			is_system=1,
			app="attention_center",
			get_count=f"{__name__}.count_nothing",
			get_items=f"{__name__}.items_nothing",
			watch_doctypes="Note",
			**values,
		)

	def count(self, key: str, user: str) -> int:
		source = frappe.db.get_value(SOURCE, key, list(registry.SOURCE_FIELDS), as_dict=True)
		frappe.set_user(user)
		try:
			return runner.run_count(source, user)["count"]
		finally:
			frappe.set_user(self.actor)

	def test_an_unwatched_doctype_takes_the_fast_path(self):
		watched = registry.get_watch_map()
		self.assertNotIn("Note", watched)
		self.assertIn("ToDo", watched)

		with patch.object(realtime, "_queue_document", wraps=realtime._queue_document) as slow_path:
			note = add_note()
			note.title = "Agenda, revised"
			note.save(ignore_permissions=True)
			frappe.delete_doc("Note", note.name, ignore_permissions=True)
			self.assertEqual(slow_path.call_count, 0)

			add_todo(self.user)
			self.assertEqual(slow_path.call_count, 1, "the handler runs for every DocType")

		note = add_note()
		with patch.object(frappe.local.db, "sql", wraps=frappe.local.db.sql) as sql:
			realtime.on_doc_event(note, "on_change")
		sql.assert_not_called()
		self.assertEqual(self.commit(), [(self.user, self.nudge(ASSIGNMENTS))])

	def test_several_changes_in_one_transaction_nudge_each_user_once_after_the_commit(self):
		add_todo(self.user, SECRET)
		add_todo(self.user, "Book the room")
		add_todo(self.other_user)
		frappe.get_doc({"doctype": "Notification Log", "subject": SECRET, "for_user": self.user}).insert(
			ignore_permissions=True
		)
		self.assertEqual(self.sent(), [], "nothing is sent before the commit")

		sent = self.commit()

		self.assertCountEqual(
			sent,
			[(self.user, self.nudge(ASSIGNMENTS, NOTIFICATIONS)), (self.other_user, self.nudge(ASSIGNMENTS))],
		)
		self.assertNotIn(SECRET, json.dumps(sent))
		self.assertEqual(self.commit(), [], "a commit without changes sends nothing")

	def test_a_reassignment_nudges_the_previous_and_the_new_assignee(self):
		todo = add_todo(self.user)
		self.commit()

		todo.allocated_to = self.other_user
		todo.save(ignore_permissions=True)

		self.assertCountEqual(
			self.commit(), [(self.user, self.nudge(ASSIGNMENTS)), (self.other_user, self.nudge(ASSIGNMENTS))]
		)

	def test_deleting_a_document_nudges_its_recipients(self):
		todo = add_todo(self.user)
		self.commit()

		frappe.delete_doc("ToDo", todo.name, ignore_permissions=True)

		self.assertEqual(self.commit(), [(self.user, self.nudge(ASSIGNMENTS))])

	def test_the_recipients_cached_counts_are_dropped_after_the_commit(self):
		add_todo(self.user)
		self.commit()
		self.assertEqual(self.count(ASSIGNMENTS, self.user), 1)
		self.assertEqual(self.count(ASSIGNMENTS, self.other_user), 0)

		add_todo(self.user, "Book the room")
		self.assertEqual(self.count(ASSIGNMENTS, self.user), 1, "cached until the change is committed")
		self.commit()

		self.assertEqual(self.count(ASSIGNMENTS, self.user), 2)
		self.assertIsNotNone(
			frappe.cache.hget(runner.COUNT_CACHE.format(ASSIGNMENTS), self.other_user),
			"the count of a user the change does not concern stays cached",
		)

	def test_an_audience_above_the_cap_is_broadcast_once_without_an_actor(self):
		notes = self.add_python_source("test_app.notes", get_recipients=f"{__name__}.note_viewers")
		viewers = tuple(make_user(f"viewer{n}@example.com", [self.role]) for n in range(3))

		with patch.object(recipients, "AUDIENCE_CAP", 2):
			add_note(viewers=viewers[:2])
		self.assertCountEqual(self.commit(), [(viewer, self.nudge(notes)) for viewer in viewers[:2]])

		self.count(notes, self.user)
		with patch.object(recipients, "AUDIENCE_CAP", 2):
			add_note(viewers=viewers)
		self.assertEqual(self.commit(), [(None, {"sources": [notes], "broadcast": True})])
		self.assertIsNone(
			frappe.cache.hget(runner.COUNT_CACHE.format(notes), self.user),
			"a broadcast drops every user's cached count of the source",
		)

	def test_a_broadcast_source_is_left_out_of_the_user_nudges(self):
		notes = self.add_python_source("test_app.notes", get_recipients=f"{__name__}.note_viewers")

		with patch.object(recipients, "AUDIENCE_CAP", 1):
			add_note(viewers=(self.user, self.other_user))
			add_note(viewers=(self.user,))
			add_todo(self.user)

		self.assertCountEqual(
			self.commit(),
			[(None, {"sources": [notes], "broadcast": True}), (self.user, self.nudge(ASSIGNMENTS))],
		)

	def test_a_source_whose_audience_is_unknown_is_broadcast(self):
		keys = [
			self.add_note_source("test_app.notes_without_recipient_fields"),
			self.add_python_source("test_app.notes_without_get_recipients"),
			self.add_python_source(
				"test_app.notes_raising", get_recipients=f"{__name__}.recipients_that_raise"
			),
			self.add_python_source(
				"test_app.notes_not_a_list", get_recipients=f"{__name__}.recipients_not_in_a_list"
			),
		]
		messages_before = list(frappe.local.message_log)

		with self.assertLogs(logger(), "ERROR") as logs:
			add_note(SECRET)

		self.assertEqual(self.commit(), [(None, {"sources": sorted(keys), "broadcast": True})])
		self.assertEqual(frappe.local.message_log, messages_before, "a failing function opens no dialog")
		self.assertEqual(
			messages(logs),
			[
				"source test_app.notes_raising: get_recipients failed for a Note change: ValidationError",
				"source test_app.notes_not_a_list: get_recipients returned str instead of a list of user ids",
			],
		)

	def test_approvals_nudge_the_enabled_holders_of_the_actions_roles(self):
		approver_role = make_desk_role("_Test Attention Approver")
		approvers = [make_user(f"approver{n}@example.com", [approver_role]) for n in range(2)]
		retired = make_user("retired.approver@example.com", [approver_role])
		frappe.db.set_value("User", retired, "enabled", 0)
		note = add_note()

		frappe.get_doc(
			{
				"doctype": "Workflow Action",
				"reference_doctype": "Note",
				"reference_name": note.name,
				"workflow_state": "Pending",
				"status": "Open",
				"permitted_roles": [{"role": approver_role}],
			}
		).insert(ignore_permissions=True)

		self.assertCountEqual(self.commit(), [(approver, self.nudge(APPROVALS)) for approver in approvers])

	def test_approvals_open_to_everyone_or_to_too_many_users_are_broadcast(self):
		approver_role = make_desk_role("_Test Attention Approver")
		for n in range(2):
			make_user(f"approver{n}@example.com", [approver_role])
		note = add_note()

		for case, role in (("implicit role", "All"), ("above the cap", approver_role)):
			with self.subTest(case):
				with patch.object(recipients, "AUDIENCE_CAP", 1):
					frappe.get_doc(
						{
							"doctype": "Workflow Action",
							"reference_doctype": "Note",
							"reference_name": note.name,
							"status": "Open",
							"permitted_roles": [{"role": role}],
						}
					).insert(ignore_permissions=True)

				self.assertEqual(self.commit(), [(None, {"sources": [APPROVALS], "broadcast": True})])

	def test_nudge_reaches_each_user_once_after_the_commit(self):
		realtime.nudge([self.user, self.other_user, self.user], ASSIGNMENTS)
		self.assertEqual(self.sent(), [], "nothing is sent before the commit")

		self.assertCountEqual(
			self.commit(), [(self.user, self.nudge(ASSIGNMENTS)), (self.other_user, self.nudge(ASSIGNMENTS))]
		)

	def test_nudge_broadcasts_above_the_cap(self):
		with patch.object(recipients, "AUDIENCE_CAP", 1):
			realtime.nudge([self.user, self.other_user], NOTIFICATIONS)

		self.assertEqual(self.commit(), [(None, {"sources": [NOTIFICATIONS], "broadcast": True})])

	def test_nudge_rejects_an_unknown_source_and_users_that_are_not_a_list(self):
		for key in ("test_app.missing", "", None, [ASSIGNMENTS]):
			with self.subTest(key=key), self.assertRaises(frappe.ValidationError):
				realtime.nudge([self.user], key)
		for users in (self.user, [self.user, None], None):
			with self.subTest(users=users), self.assertRaises(frappe.ValidationError):
				realtime.nudge(users, ASSIGNMENTS)

		self.assertEqual(self.commit(), [])

	def test_a_rolled_back_transaction_nudges_nobody(self):
		add_todo(self.user)

		frappe.db.rollback()
		registry.sync_sources()
		realtime.nudge(["late@example.com"], ASSIGNMENTS)

		self.assertEqual(self.commit(), [("late@example.com", self.nudge(ASSIGNMENTS))])

	def test_install_migrate_and_import_send_nothing(self):
		for flag in ("in_install", "in_migrate", "in_import"):
			with self.subTest(flag), patch.dict(frappe.flags, {flag: True}):
				add_todo(self.user)

				self.assertEqual(self.commit(), [])

	def test_a_failure_neither_stops_the_save_nor_the_commit(self):
		with patch.object(registry, "get_watch_map", side_effect=RuntimeError(SECRET)):
			with self.assertLogs(logger(), "ERROR") as logs:
				todo = add_todo(self.user)
		self.assertTrue(frappe.db.exists("ToDo", todo.name))
		self.assertEqual(messages(logs), ["nudges for a ToDo change failed: RuntimeError"])

		add_todo(self.user)
		with patch.object(frappe.cache, "hdel", side_effect=RuntimeError(SECRET)):
			with self.assertLogs(logger(), "ERROR") as logs:
				self.assertEqual(self.commit(), [])
		self.assertEqual(messages(logs), ["sending nudges failed: RuntimeError"])

	def test_the_watch_map_follows_source_changes(self):
		self.assertNotIn("Note", registry.get_watch_map())

		notes = self.add_note_source("test_app.my_notes", recipient_fields="owner")
		self.assertEqual([source.key for source in registry.get_watch_map()["Note"]], [notes])
		add_note()
		self.assertEqual(self.commit(), [(self.actor, self.nudge(notes))])

		frappe.set_user("Administrator")
		source = frappe.get_doc(SOURCE, notes)
		source.enabled = 0
		source.save()
		frappe.set_user(self.actor)
		self.assertNotIn("Note", registry.get_watch_map())
