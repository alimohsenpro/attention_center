"""The managers' desk: the two forms and the workspace that leads to them [FR-SET-01, FR-SET-03]."""

import json

import frappe
from frappe.desk.desktop import get_workspace_sidebar_items
from frappe.desk.form.load import getdoc
from frappe.tests.utils import FrappeTestCase

from attention_center.tests.utils import make_desk_role, make_user

SETTINGS = "Attention Center Settings"
SOURCE = "Attention Source"
WORKSPACE = "Attention Center"
SOURCE_KEY = "test_app.admin_todos"


def open_form(doctype: str, name: str) -> dict:
	"""What the desk receives when it opens a form."""
	frappe.local.response = frappe._dict(docs=[])
	getdoc(doctype, name)
	return frappe.response.docs[0].as_dict()


def declared_tones() -> list[dict]:
	with open(frappe.get_app_path("attention_center", "public", "sounds", "tones.json")) as file:
		return json.load(file)


class TestAdminDesk(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.manager = make_user("admin.manager@example.com", ["Attention Manager"])
		self.system_manager = make_user("admin.system@example.com", ["System Manager"])
		self.desk_user = make_user("admin.user@example.com", [make_desk_role("_Test Attention Admin Role")])
		frappe.get_doc(
			{
				"doctype": SOURCE,
				"key": SOURCE_KEY,
				"label": "Open tasks",
				"kind": "Action",
				"reference_doctype": "ToDo",
				"title_field": "description",
				"date_field": "creation",
			}
		).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_managers_open_both_forms(self):
		for user in (self.manager, self.system_manager):
			frappe.set_user(user)
			with self.subTest(user=user):
				self.assertEqual(open_form(SETTINGS, SETTINGS)["name"], SETTINGS)
				self.assertEqual(open_form(SOURCE, SOURCE_KEY)["label"], "Open tasks")

	def test_other_desk_users_cannot_open_the_forms(self):
		frappe.set_user(self.desk_user)

		for doctype, name in ((SETTINGS, SETTINGS), (SOURCE, SOURCE_KEY)):
			with self.subTest(doctype=doctype), self.assertRaises(frappe.PermissionError):
				open_form(doctype, name)
		self.assertFalse(frappe.has_permission(SOURCE, "create"))

	def test_the_settings_form_lists_the_tones_of_tones_json_with_translated_labels(self):
		frappe.set_user(self.manager)

		tones = open_form(SETTINGS, SETTINGS)["__onload"]["tones"]

		self.assertEqual(tones, [{"value": tone["id"], "label": tone["label"]} for tone in declared_tones()])
		lang = frappe.local.lang
		frappe.local.lang = "ar"
		try:
			arabic = open_form(SETTINGS, SETTINGS)["__onload"]["tones"]
		finally:
			frappe.local.lang = lang
		self.assertEqual(arabic[0], {"value": "chime", "label": "رنين"})

	def test_the_workspace_is_listed_for_managers_only(self):
		for user, listed in ((self.manager, True), (self.system_manager, True), (self.desk_user, False)):
			frappe.set_user(user)
			with self.subTest(user=user):
				pages = [page["name"] for page in get_workspace_sidebar_items()["pages"]]
				self.assertEqual(WORKSPACE in pages, listed)

	def test_the_workspace_leads_to_the_settings_and_the_sources(self):
		shortcuts = frappe.get_doc("Workspace", WORKSPACE).shortcuts

		self.assertEqual(
			[(shortcut.type, shortcut.link_to) for shortcut in shortcuts],
			[("DocType", SETTINGS), ("DocType", SOURCE)],
		)
