# Copyright (c) 2026, Attention Center Contributors and Contributors
# See license.txt

import json

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase

from attention_center.tests.utils import make_desk_role, make_user

SETTINGS = "Attention Center Settings"
DEFAULTS = {
	"enabled": 1,
	"default_display_mode": "Dialog",
	"default_auto_open_on_login": 1,
	"default_sound_scope": "Action Items",
	"default_tone": "chime",
	"default_volume": 60,
	"urgent_tone": "urgent",
	"immediate_tone": "immediate",
	"reminder_tone": "reminder",
	"reminder_interval_hours": 2.0,
	"coalesce_seconds": 10,
	"heartbeat_seconds": 300,
	"summary_cache_ttl": 60,
	"page_size": 10,
	"hide_standard_bell": 0,
}
BOUNDS = {
	"default_volume": (0, 100),
	"coalesce_seconds": (1, 120),
	"heartbeat_seconds": (60, 3600),
	"summary_cache_ttl": (5, 600),
	"page_size": (5, 50),
}
TONE_FIELDS = ("default_tone", "urgent_tone", "immediate_tone", "reminder_tone")


def settings(**values) -> Document:
	doc = frappe.get_single(SETTINGS)
	doc.update({**DEFAULTS, **values})
	return doc


class TestAttentionCenterSettings(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_document_cache(SETTINGS, SETTINGS)

	def test_defaults_follow_the_design_and_are_valid(self):
		self.assertDocumentEqual(DEFAULTS, frappe.new_doc(SETTINGS))
		settings().save()

	def test_tone_fields_offer_the_bundled_tones_with_role_defaults(self):
		with open(frappe.get_app_path("attention_center", "public", "sounds", "tones.json")) as f:
			tones = json.load(f)
		first_tone_by_role = {}
		for tone in tones:
			first_tone_by_role.setdefault(tone["role"], tone["id"])
		meta = frappe.get_meta(SETTINGS)

		for fieldname in TONE_FIELDS:
			with self.subTest(fieldname):
				self.assertEqual(meta.get_options(fieldname).split("\n"), [tone["id"] for tone in tones])
		self.assertEqual(
			[meta.get_field(fieldname).default for fieldname in TONE_FIELDS],
			[first_tone_by_role[role] for role in ("standard", "urgent", "immediate", "reminder")],
		)

	def test_bounded_numbers_accept_their_limits(self):
		for fieldname, limits in BOUNDS.items():
			for value in limits:
				with self.subTest(fieldname=fieldname, value=value):
					settings(**{fieldname: value}).save()

	def test_bounded_numbers_reject_values_outside_their_limits(self):
		for fieldname, (low, high) in BOUNDS.items():
			for value in (low - 1, high + 1):
				with self.subTest(fieldname=fieldname, value=value):
					with self.assertRaisesRegex(frappe.ValidationError, "must be between"):
						settings(**{fieldname: value}).save()

	def test_bound_messages_name_fields_in_the_app_wording(self):
		lang = frappe.local.lang
		frappe.local.lang = "ar"
		try:
			with self.assertRaisesRegex(frappe.ValidationError, "عدد العناصر في الصفحة"):
				settings(page_size=51).save()
		finally:
			frappe.local.lang = lang

	def test_reminder_interval_is_off_or_at_least_a_quarter_hour(self):
		for hours in (0, 0.25, 2, 24):
			with self.subTest(hours=hours):
				settings(reminder_interval_hours=hours).save()

		for hours in (-1, 0.1, 0.24):
			with self.subTest(hours=hours):
				with self.assertRaisesRegex(frappe.ValidationError, "at least 0.25"):
					settings(reminder_interval_hours=hours).save()

	def test_unknown_tone_is_rejected(self):
		for fieldname in TONE_FIELDS:
			with self.subTest(fieldname):
				with self.assertRaises(frappe.ValidationError):
					settings(**{fieldname: "no_such_tone"}).save()

	def test_only_managers_can_read_and_change_settings(self):
		manager = make_user("settings.manager@example.com", ["Attention Manager"])
		system_manager = make_user("settings.admin@example.com", ["System Manager"])
		desk_user = make_user("settings.user@example.com", [make_desk_role("_Test Attention Desk Role")])

		for user in (manager, system_manager):
			with self.subTest(user=user):
				self.assertTrue(frappe.has_permission(SETTINGS, "read", user=user))
				frappe.set_user(user)
				settings(page_size=20).save()

		frappe.set_user("Administrator")
		self.assertFalse(frappe.has_permission(SETTINGS, "read", user=desk_user))
		frappe.set_user(desk_user)
		with self.assertRaises(frappe.PermissionError):
			settings(page_size=30).save()
