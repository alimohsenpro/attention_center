import frappe
from frappe.tests.utils import FrappeTestCase


class TestInstall(FrappeTestCase):
	def test_app_is_installed_with_its_module(self):
		self.assertIn("attention_center", frappe.get_installed_apps())
		module_owner = frappe.db.get_value("Module Def", "Attention Center", "app_name")
		self.assertEqual(module_owner, "attention_center")
