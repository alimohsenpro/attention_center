import frappe
from frappe.tests.utils import FrappeTestCase


class TestInstall(FrappeTestCase):
	def test_app_is_installed_with_its_module(self):
		self.assertIn("attention_center", frappe.get_installed_apps())
		self.assertTrue(frappe.db.exists("Module Def", "Attention Center"))
