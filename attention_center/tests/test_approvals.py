from datetime import datetime

import frappe
from frappe.model.workflow import apply_workflow
from frappe.permissions import add_user_permission
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from attention_center.engine import registry, runner
from attention_center.sources import approvals
from attention_center.tests.utils import make_desk_role, make_user

KEY = "attention_center.approvals"
# Created in setUpClass and dropped in tearDownClass: DocType changes commit, so a test cannot roll them back.
EXPENSE = "Attention Test Expense"
WORKFLOW = "Attention Test Expense Approval"
APPROVER = "_Test Attention Expense Approver"
READER = "_Test Attention Expense Reader"
PENDING = "Attention Test Pending"
APPROVED = "Attention Test Approved"
APPROVE = "Attention Test Approve"


def create_expense_workflow() -> None:
	for role in (APPROVER, READER):
		if not frappe.db.exists("Role", role):
			make_desk_role(role)
	for state in (PENDING, APPROVED):
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert()
	if not frappe.db.exists("Workflow Action Master", APPROVE):
		frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": APPROVE}).insert()

	if frappe.db.exists("DocType", EXPENSE):
		frappe.delete_doc("DocType", EXPENSE, force=True)
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": EXPENSE,
			"module": "Custom",
			"custom": 1,
			"title_field": "subject",
			"fields": [
				{"fieldname": "subject", "fieldtype": "Data", "label": "Subject"},
				# Declared here so that the workflow does not add it as a Custom Field.
				{
					"fieldname": "workflow_state",
					"fieldtype": "Link",
					"options": "Workflow State",
					"label": "Workflow State",
				},
			],
			"permissions": [{"role": READER, "read": 1, "write": 1, "create": 1}],
		}
	).insert()
	frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": WORKFLOW,
			"document_type": EXPENSE,
			"workflow_state_field": "workflow_state",
			"is_active": 1,
			"send_email_alert": 0,
			"states": [
				{"state": PENDING, "doc_status": "0", "allow_edit": READER},
				{"state": APPROVED, "doc_status": "0", "allow_edit": APPROVER},
			],
			"transitions": [
				{
					"state": PENDING,
					"action": APPROVE,
					"next_state": APPROVED,
					"allowed": APPROVER,
					"allow_self_approval": 1,
				}
			],
		}
	).insert()


def drop_expense_workflow() -> None:
	frappe.delete_doc("Workflow", WORKFLOW, force=True)
	frappe.delete_doc("DocType", EXPENSE, force=True)
	# Frappe keeps the table of a deleted DocType; this test's table goes with it.
	frappe.db.sql_ddl(f"drop table if exists `tab{EXPENSE}`")
	frappe.db.delete("Workflow Action", {"reference_doctype": EXPENSE})
	for doctype, name in (
		("Workflow Action Master", APPROVE),
		("Workflow State", PENDING),
		("Workflow State", APPROVED),
		("Role", APPROVER),
		("Role", READER),
	):
		frappe.delete_doc(doctype, name, force=True)


def add_expense(subject: str) -> str:
	"""An expense entering the workflow, which opens one Workflow Action for the approver role."""
	return frappe.get_doc({"doctype": EXPENSE, "subject": subject}).insert(ignore_permissions=True).name


def open_action(expense: str) -> str:
	return frappe.db.get_value(
		"Workflow Action", {"reference_doctype": EXPENSE, "reference_name": expense, "status": "Open"}
	)


def set_action_creation(action: str, creation: datetime) -> None:
	frappe.db.set_value("Workflow Action", action, "creation", creation, update_modified=False)


class TestApprovals(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_expense_workflow()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		drop_expense_workflow()
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		registry.sync_sources()
		self.source = frappe.db.get_value("Attention Source", KEY, list(registry.SOURCE_FIELDS), as_dict=True)
		self.approver = make_user("expense.approver@example.com", [APPROVER, READER])

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.cache.delete_value(runner.COUNT_CACHE.format(KEY))
		# User Permissions are cached per user and a rollback does not clear the cache.
		frappe.cache.delete_value("user_permissions")

	def summary(self, user: str) -> dict:
		frappe.cache.delete_value(runner.COUNT_CACHE.format(KEY))
		frappe.set_user(user)
		try:
			result = runner.run_count(self.source, user)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(result["state"], "ok")
		return result

	def items(self, user: str, start: int = 0, page_length: int = 50) -> list[dict]:
		frappe.set_user(user)
		try:
			result = runner.run_items(self.source, user, start, page_length)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(result["state"], "ok")
		return result["items"]

	def titles(self, user: str, start: int = 0, page_length: int = 50) -> list[str]:
		return [item["title"] for item in self.items(user, start, page_length)]

	def test_a_role_holder_who_can_read_the_document_sees_it_once(self):
		expense = add_expense("<b>Taxi</b> to the airport")
		action = open_action(expense)
		created = frappe.db.get_value("Workflow Action", action, "creation")
		older = frappe.get_doc(
			{
				"doctype": "Workflow Action",
				"reference_doctype": EXPENSE,
				"reference_name": expense,
				"workflow_state": PENDING,
				"status": "Open",
				"permitted_roles": [{"role": READER}],
			}
		).insert(ignore_permissions=True)
		set_action_creation(older.name, add_to_date(created, hours=-1))

		self.assertEqual(
			self.items(self.approver),
			[
				{
					"id": action,
					"title": "Taxi to the airport",
					"route": f"/app/attention-test-expense/{expense}",
					"reference_doctype": EXPENSE,
					"reference_name": expense,
					"type_label": EXPENSE,
					"from_label": None,
					"date": created.isoformat(timespec="seconds"),
					"priority": "normal",
					"due": None,
					"overdue": False,
					"status_label": PENDING,
					"status_color": "gray",
				}
			],
		)
		self.assertEqual(self.summary(self.approver)["count"], 1)

	def test_a_role_holder_who_cannot_read_the_document_sees_nothing(self):
		add_expense("Hotel")
		blind_approver = make_user("blind.approver@example.com", [APPROVER])

		self.assertEqual(self.items(blind_approver), [])
		self.assertEqual(self.summary(blind_approver)["count"], 0)
		self.assertEqual(self.titles(self.approver), ["Hotel"])

	def test_read_permission_is_checked_on_each_document(self):
		allowed = add_expense("Allowed expense")
		add_expense("Other expense")
		restricted = make_user("restricted.approver@example.com", [APPROVER, READER])
		add_user_permission(EXPENSE, allowed, restricted)

		self.assertEqual(self.titles(restricted), ["Allowed expense"])
		self.assertEqual(self.summary(restricted)["count"], 1)
		self.assertCountEqual(self.titles(self.approver), ["Allowed expense", "Other expense"])

	def test_a_reader_without_the_workflow_role_sees_nothing(self):
		add_expense("Hotel")
		reader = make_user("expense.reader@example.com", [READER])

		self.assertEqual(self.items(reader), [])
		self.assertEqual(self.summary(reader)["count"], 0)

	def test_completed_actions_disappear(self):
		approved = add_expense("Approved expense")
		add_expense("Waiting expense")
		self.assertEqual(self.summary(self.approver)["count"], 2)

		apply_workflow(frappe.get_doc(EXPENSE, approved), APPROVE)

		self.assertEqual(
			frappe.db.get_value("Workflow Action", {"reference_name": approved}, "status"), "Completed"
		)
		self.assertEqual(self.titles(self.approver), ["Waiting expense"])
		self.assertEqual(self.summary(self.approver)["count"], 1)

	def test_items_come_newest_first_and_page_without_overlap(self):
		now = now_datetime()
		for hours_ago, subject in ((3, "Oldest"), (1, "Newest"), (2, "Middle")):
			set_action_creation(open_action(add_expense(subject)), add_to_date(now, hours=-hours_ago))

		self.assertEqual(self.titles(self.approver), ["Newest", "Middle", "Oldest"])
		self.assertEqual(
			[self.titles(self.approver, start, 2) for start in (0, 2, 4)],
			[["Newest", "Middle"], ["Oldest"], []],
		)

	def test_the_count_carries_the_latest_action_and_the_actions_new_since_the_watermark(self):
		now = now_datetime().replace(microsecond=0)
		newest = add_to_date(now, hours=-1)
		set_action_creation(open_action(add_expense("Newest")), newest)
		set_action_creation(open_action(add_expense("Older")), add_to_date(now, hours=-3))
		frappe.set_user(self.approver)

		counts = approvals.get_count(self.approver, since=add_to_date(now, hours=-2))
		without_watermark = approvals.get_count(self.approver)

		self.assertEqual(counts, {"count": 2, "latest": newest, "new_since": 1})
		self.assertEqual(without_watermark["new_since"], 2, "no watermark: every document is new")

	def test_an_action_whose_document_is_gone_is_skipped_quietly(self):
		add_expense("Kept expense")
		frappe.db.delete(EXPENSE, {"name": add_expense("Deleted expense")})
		queued_messages = len(frappe.local.message_log)

		self.assertEqual(self.titles(self.approver), ["Kept expense"])
		self.assertEqual(self.summary(self.approver)["count"], 1)
		self.assertEqual(len(frappe.local.message_log), queued_messages)

	def test_an_action_whose_doctype_is_gone_is_skipped_quietly(self):
		add_expense("Kept expense")
		orphan = open_action(add_expense("Orphaned expense"))
		frappe.db.set_value("Workflow Action", orphan, "reference_doctype", "Attention Test Deleted DocType")
		queued_messages = len(frappe.local.message_log)

		self.assertEqual(self.titles(self.approver), ["Kept expense"])
		self.assertEqual(self.summary(self.approver)["count"], 1)
		self.assertEqual(len(frappe.local.message_log), queued_messages)

	def test_the_title_falls_back_to_the_name_when_the_user_may_not_read_the_title_field(self):
		expense = add_expense("Confidential subject")
		frappe.make_property_setter(
			{"doctype": EXPENSE, "fieldname": "subject", "property": "permlevel", "value": "1"},
			validate_fields_for_doctype=False,
		)
		# Runs after tearDown: the rollback removes the property setter but not the cached meta.
		self.addCleanup(frappe.clear_cache, doctype=EXPENSE)

		self.assertEqual(self.titles(self.approver), [expense])
