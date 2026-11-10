import frappe
from frappe.tests.utils import FrappeTestCase

from attention_center.install import after_migrate

SETTINGS = "Attention Center Settings"
DOCTYPES = (
	"Attention Center Settings",
	"Attention Source",
	"Attention Source Role",
	"Attention Source User Group",
	"Attention User Preference",
)


def stored_setting(fieldname: str) -> object:
	return frappe.db.get_single_value(SETTINGS, fieldname, cache=False)


class TestInstall(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_document_cache(SETTINGS, SETTINGS)

	def test_app_is_installed_with_its_module(self):
		self.assertIn("attention_center", frappe.get_installed_apps())
		module_owner = frappe.db.get_value("Module Def", "Attention Center", "app_name")
		self.assertEqual(module_owner, "attention_center")

	def test_doctypes_are_installed_in_the_module(self):
		for doctype in DOCTYPES:
			with self.subTest(doctype):
				self.assertEqual(frappe.db.get_value("DocType", doctype, "module"), "Attention Center")

	def test_attention_manager_role_is_installed_with_desk_access(self):
		role = frappe.db.get_value("Role", "Attention Manager", ["desk_access", "disabled"], as_dict=True)

		self.assertEqual((role.desk_access, role.disabled), (1, 0))

	def test_migrate_fills_missing_settings_defaults_and_keeps_admin_values(self):
		frappe.db.set_single_value(SETTINGS, "page_size", 25)
		frappe.db.delete("Singles", {"doctype": SETTINGS, "field": ("in", ("heartbeat_seconds", "enabled"))})
		frappe.get_cached_doc(SETTINGS)

		after_migrate()

		self.assertEqual((stored_setting("heartbeat_seconds"), stored_setting("enabled")), (300, 1))
		self.assertEqual(stored_setting("page_size"), 25)
		self.assertEqual(frappe.get_cached_doc(SETTINGS).heartbeat_seconds, 300)
