import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from attention_center.engine import registry, runner
from attention_center.sources import builtin
from attention_center.tests.utils import make_desk_role, make_user

SOURCE = "Attention Source"
APPROVALS = "attention_center.approvals"
ASSIGNMENTS = "attention_center.assignments"
NOTIFICATIONS = "attention_center.notifications"
ANNOUNCEMENTS = "attention_center.announcements"
BUILT_IN = (APPROVALS, ASSIGNMENTS, NOTIFICATIONS, ANNOUNCEMENTS)


def add_note(title: str) -> str:
	return frappe.get_doc({"doctype": "Note", "title": title}).insert(ignore_permissions=True).name


def creation(doctype: str, name: str) -> str:
	return frappe.db.get_value(doctype, name, "creation").isoformat(timespec="seconds")


class BuiltinSourceTestCase(FrappeTestCase):
	key: str

	def setUp(self):
		registry.sync_sources()
		self.source = frappe.db.get_value(SOURCE, self.key, list(registry.SOURCE_FIELDS), as_dict=True)
		role = make_desk_role("_Test Attention Desk User")
		self.user = make_user("attention.user@example.com", [role])
		self.other_user = make_user("other.user@example.com", [role])
		self.sender = make_user("sender@example.com", [role])

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.cache.delete_value(runner.COUNT_CACHE.format(self.key))

	def summary(self, user: str) -> dict:
		frappe.cache.delete_value(runner.COUNT_CACHE.format(self.key))
		frappe.set_user(user)
		try:
			result = runner.run_count(self.source, user)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(result["state"], "ok")
		return result

	def items(self, user: str) -> list[dict]:
		frappe.set_user(user)
		try:
			result = runner.run_items(self.source, user, 0, 50)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(result["state"], "ok")
		return result["items"]


class TestRegistration(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		registry.clear_visibility_cache()

	def test_this_apps_hooks_declare_the_built_in_sources(self):
		declared = {
			source["key"]: source["app"]
			for source in registry.load_hook_sources()
			if source["app"] == "attention_center"
		}

		self.assertEqual(declared, dict.fromkeys(BUILT_IN, "attention_center"))
		self.assertEqual([source["key"] for source in builtin.SOURCES], list(BUILT_IN))

	def test_the_sync_stores_them_as_enabled_system_sources_every_desk_user_sees(self):
		frappe.db.delete(SOURCE, {"name": ("in", BUILT_IN)})
		user = make_user("desk.user@example.com", [make_desk_role("_Test Attention Desk User")])

		registry.sync_sources()

		self.assertEqual(
			list(
				frappe.get_all(
					SOURCE,
					filters={"name": ("in", BUILT_IN)},
					fields=["name", "kind", "source_type", "enabled", "is_system"],
					order_by="name",
					as_list=True,
				)
			),
			[
				(ANNOUNCEMENTS, "Action", "Python", 1, 1),
				(APPROVALS, "Action", "Python", 1, 1),
				(ASSIGNMENTS, "Action", "DocType Query", 1, 1),
				(NOTIFICATIONS, "Info", "DocType Query", 1, 1),
			],
		)
		visible = [source.key for source in registry.get_visible_sources(user)]
		self.assertEqual([key for key in visible if key.startswith("attention_center.")], list(BUILT_IN))


class TestAssignments(BuiltinSourceTestCase):
	key = ASSIGNMENTS

	def add_todo(self, description: str, allocated_to: str | None = None, **values) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "ToDo",
					"description": description,
					"allocated_to": allocated_to or self.user,
					**values,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_an_item_opens_the_referenced_document_and_carries_the_mapped_fields(self):
		note = add_note("Quarterly report")
		yesterday = add_days(today(), -1)
		todo = self.add_todo(
			"<p>Check the <b>quarterly</b> report</p>",
			assigned_by=self.sender,
			priority="High",
			date=yesterday,
			reference_type="Note",
			reference_name=note,
		)

		self.assertEqual(
			self.items(self.user),
			[
				{
					"id": todo,
					"title": "Check the quarterly report",
					"route": f"/app/note/{note}",
					"type_label": None,
					"from_label": "sender",
					"date": creation("ToDo", todo),
					"priority": "urgent",
					"due": yesterday,
					"overdue": True,
					"status_label": None,
					"status_color": "gray",
				}
			],
		)

	def test_an_assignment_without_a_reference_opens_the_todo(self):
		todo = self.add_todo("Call the supplier")

		self.assertEqual([item["route"] for item in self.items(self.user)], [f"/app/todo/{todo}"])

	def test_high_maps_to_urgent_and_the_todo_date_is_the_due_date(self):
		self.add_todo("High, due yesterday", priority="High", date=add_days(today(), -1))
		self.add_todo("High, due today", priority="High", date=today())
		self.add_todo("Medium, due yesterday", priority="Medium", date=add_days(today(), -1))
		self.add_todo("Low, no date", priority="Low")

		summary = self.summary(self.user)
		items = {item["title"]: (item["priority"], item["overdue"]) for item in self.items(self.user)}

		self.assertEqual((summary["count"], summary["urgent"], summary["overdue"]), (4, 2, 2))
		self.assertEqual(
			items,
			{
				"High, due yesterday": ("urgent", True),
				"High, due today": ("urgent", False),
				"Medium, due yesterday": ("normal", True),
				"Low, no date": ("normal", False),
			},
		)

	def test_closed_assignments_and_other_users_rows_are_invisible(self):
		self.add_todo("Mine")
		self.add_todo("Mine, closed", status="Closed")
		self.add_todo("Mine, cancelled", status="Cancelled")
		self.add_todo("Theirs", allocated_to=self.other_user)

		self.assertEqual([item["title"] for item in self.items(self.user)], ["Mine"])
		self.assertEqual(self.summary(self.user)["count"], 1)
		self.assertEqual([item["title"] for item in self.items(self.other_user)], ["Theirs"])
		self.assertEqual(self.summary(self.other_user)["count"], 1)


class TestNotifications(BuiltinSourceTestCase):
	key = NOTIFICATIONS

	def add_log(self, subject: str, for_user: str | None = None, **values) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"subject": subject,
					"for_user": for_user or self.user,
					**values,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_an_item_opens_the_referenced_document_and_carries_the_mapped_fields(self):
		note = add_note("Budget")
		log = self.add_log(
			"<b>Budget</b> was shared with you",
			from_user=self.sender,
			document_type="Note",
			document_name=note,
		)

		self.assertEqual(
			self.items(self.user),
			[
				{
					"id": log,
					"title": "Budget was shared with you",
					"route": f"/app/note/{note}",
					"type_label": None,
					"from_label": "sender",
					"date": creation("Notification Log", log),
					"priority": "normal",
					"due": None,
					"overdue": False,
					"status_label": None,
					"status_color": "gray",
				}
			],
		)

	def test_the_route_is_the_link_then_the_reference_then_the_log(self):
		note = add_note("Budget")
		reference = {"document_type": "Note", "document_name": note}
		desk_link = self.add_log("Desk link", link="/app/todo?status=Open", **reference)
		outside_link = self.add_log("Link outside the desk", link="https://example.com/report", **reference)
		reference_only = self.add_log("Reference only", **reference)
		half_reference = self.add_log("Document type only", document_type="Note")
		bare = self.add_log("No link or reference")

		routes = {item["id"]: item["route"] for item in self.items(self.user)}

		self.assertEqual(
			routes,
			{
				desk_link: "/app/todo?status=Open",
				outside_link: f"/app/note/{note}",
				reference_only: f"/app/note/{note}",
				half_reference: f"/app/notification-log/{half_reference}",
				bare: f"/app/notification-log/{bare}",
			},
		)

	def test_read_logs_and_other_users_logs_are_invisible(self):
		self.add_log("Unread")
		self.add_log("Read", read=1)
		self.add_log("For someone else", for_user=self.other_user)

		self.assertEqual([item["title"] for item in self.items(self.user)], ["Unread"])
		self.assertEqual(self.summary(self.user)["count"], 1)
		self.assertEqual([item["title"] for item in self.items(self.other_user)], ["For someone else"])
		self.assertEqual(self.summary(self.other_user)["count"], 1)
