import gzip
import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.jinja_globals import bundled_asset

from attention_center.install import after_migrate

SETTINGS = "Attention Center Settings"
# NFR-PERF-02: the launcher bundle, loaded on every desk page, at most this many bytes gzipped.
LAUNCHER_GZIP_LIMIT = 25 * 1024
# A text of the window only (its title): the launcher bundle must not carry the window's code.
WINDOW_TEXT = b"What needs your attention"
DOCTYPES = (
	"Attention Center Settings",
	"Attention Source",
	"Attention Source Role",
	"Attention Source User Group",
	"Attention User Preference",
)


def built_bundle(name: str) -> bytes:
	with open(os.path.join(frappe.local.sites_path, bundled_asset(name).lstrip("/")), "rb") as file:
		return file.read()


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

	def test_desk_pages_load_the_built_launcher_bundle(self):
		self.assertIn("attention_center.bundle.js", frappe.get_hooks("app_include_js"))
		# The desk resolves the bundle name through assets.json, which the build writes.
		self.assertRegex(
			bundled_asset("attention_center.bundle.js"),
			r"^/assets/attention_center/dist/js/attention_center\.bundle\.\w+\.js$",
		)

	def test_the_launcher_bundle_is_small_and_leaves_the_window_to_its_own_bundle(self):
		launcher = built_bundle("attention_center.bundle.js")

		self.assertLessEqual(len(gzip.compress(launcher)), LAUNCHER_GZIP_LIMIT)
		# assertNotIn and assertIn would print the whole bundle.
		self.assertFalse(WINDOW_TEXT in launcher, "the launcher bundle carries the window's code")
		self.assertTrue(
			WINDOW_TEXT in built_bundle("attention_center_window.bundle.js"),
			"the window bundle lacks the window's title",
		)

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
