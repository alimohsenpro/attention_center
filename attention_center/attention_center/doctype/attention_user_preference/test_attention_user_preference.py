# Copyright (c) 2026, Attention Center Contributors and Contributors
# See license.txt

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase

from attention_center.tests.utils import make_desk_role, make_user

PREFERENCE = "Attention User Preference"


def preference(user: str, **values) -> Document:
	return frappe.get_doc({"doctype": PREFERENCE, "user": user, **values})


class TestAttentionUserPreference(FrappeTestCase):
	def setUp(self):
		self.user = make_user("preference.user@example.com", [make_desk_role("_Test Attention Desk Role")])

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_preference_is_named_after_its_user_and_unique(self):
		doc = preference(self.user).insert()

		self.assertEqual(doc.name, self.user)
		with self.assertRaises(frappe.DuplicateEntryError):
			preference(self.user).insert()

	def test_new_preference_inherits_every_setting(self):
		preference(self.user).insert()

		self.assertDocumentEqual(
			{
				"sound_scope": "",
				"tone": "",
				"volume": None,
				"dnd_until": None,
				"auto_open_on_login": "Default",
				"display_mode": "Default",
				"launcher_collapsed": 0,
			},
			frappe.get_doc(PREFERENCE, self.user),
		)

	def test_volume_is_empty_or_a_whole_number_up_to_100(self):
		accepted = {"": None, None: None, "0": "0", "100": "100", " 55 ": "55", "007": "7", 40: "40"}
		for value, stored in accepted.items():
			with self.subTest(value=value):
				doc = preference(self.user, volume=value).insert()
				self.assertEqual(doc.volume, stored)
				doc.delete()

		for value in ("-1", "101", "1000", "loud", "50.5", "\u0665\u0660"):
			with self.subTest(value=value):
				with self.assertRaisesRegex(frappe.ValidationError, "Volume"):
					preference(self.user, volume=value).insert()

	def test_choices_are_limited_to_their_options(self):
		for fieldname in ("sound_scope", "tone", "auto_open_on_login", "display_mode"):
			with self.subTest(fieldname):
				with self.assertRaises(frappe.ValidationError):
					preference(self.user, **{fieldname: "Sometimes"}).insert()

	def test_desk_access_is_read_only_for_system_managers_and_none_for_users(self):
		preference(self.user).insert()
		system_manager = make_user("preference.admin@example.com", ["System Manager"])

		self.assertTrue(frappe.has_permission(PREFERENCE, "read", user=system_manager))
		for ptype in ("write", "create", "delete"):
			with self.subTest(ptype=ptype):
				self.assertFalse(frappe.has_permission(PREFERENCE, ptype, user=system_manager))

		self.assertFalse(frappe.has_permission(PREFERENCE, "read", doc=self.user, user=self.user))
		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list(PREFERENCE)
