# Copyright (c) 2026, Attention Center Contributors and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime

from attention_center.tests.utils import make_desk_role, make_user

ANNOUNCEMENT = "Attention Announcement"
RECEIPT = "Attention Announcement Receipt"


def make_announcement(**values) -> frappe.model.document.Document:
	return frappe.get_doc({"doctype": ANNOUNCEMENT, "title": "Office closed on Friday", **values}).insert()


class TestAttentionAnnouncement(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_the_body_is_sanitised_on_save_even_when_the_field_skips_the_xss_filter(self):
		frappe.make_property_setter(
			{"doctype": ANNOUNCEMENT, "fieldname": "body", "property": "ignore_xss_filter", "value": "1"},
			validate_fields_for_doctype=False,
		)
		# Runs after tearDown: the rollback removes the property setter but not the cached meta.
		self.addCleanup(frappe.clear_cache, doctype=ANNOUNCEMENT)
		self.assertTrue(frappe.get_meta(ANNOUNCEMENT).get_field("body").ignore_xss_filter)

		body = make_announcement(
			body='<p onclick="steal()">Read <b>this</b></p><script>steal()</script><img src="x" onerror="steal()">'
		).body

		self.assertIn("<b>this</b>", body)
		self.assertNotIn("<script", body)
		self.assertNotIn("onerror", body)
		self.assertNotIn("onclick", body)

	def test_publishing_starts_the_window_at_the_moment_of_publishing(self):
		before = now_datetime()
		future = add_to_date(before, days=2).replace(microsecond=0)
		cases = (
			("no start", None, "now"),
			("a start in the past", add_to_date(before, days=-3), "now"),
			("a start in the future", future, future),
		)
		for case, valid_from, expected in cases:
			with self.subTest(case):
				announcement = make_announcement(published=1, valid_from=valid_from)
				valid_from = get_datetime(announcement.valid_from)
				if expected == "now":
					self.assertTrue(before <= valid_from <= now_datetime())
				else:
					self.assertEqual(valid_from, expected)

	def test_a_draft_keeps_its_start_and_a_published_announcement_keeps_it_when_edited(self):
		past = add_to_date(now_datetime(), days=-3).replace(microsecond=0)
		draft = make_announcement(valid_from=past)
		self.assertEqual(get_datetime(draft.valid_from), past)

		draft.published = 1
		draft.save()
		published_at = get_datetime(draft.valid_from)
		self.assertGreater(published_at, past)

		draft.title = "Office closed on Friday afternoon"
		draft.save()
		self.assertEqual(get_datetime(draft.valid_from), published_at)

	def test_the_window_must_end_after_it_starts(self):
		start = add_to_date(now_datetime(), days=1)
		for valid_to in (start, add_to_date(start, hours=-1)):
			with self.subTest(valid_to=valid_to), self.assertRaises(frappe.ValidationError):
				make_announcement(valid_from=start, valid_to=valid_to)

		self.assertTrue(make_announcement(valid_from=start, valid_to=add_to_date(start, hours=1)).name)

	def test_a_published_announcement_needs_an_audience(self):
		with self.assertRaises(frappe.ValidationError):
			make_announcement(published=1, all_users=0)

		self.assertTrue(make_announcement(published=0, all_users=0).name)
		role = make_desk_role("_Test Attention Announcement Audience")
		self.assertTrue(make_announcement(published=1, all_users=0, roles=[{"role": role}]).name)

	def test_roles_every_user_holds_are_refused(self):
		for role in ("All", "Desk User", "Guest"):
			with self.subTest(role=role), self.assertRaises(frappe.ValidationError):
				make_announcement(all_users=0, roles=[{"role": role}])

	def test_a_user_has_one_receipt_per_announcement(self):
		announcement = make_announcement(published=1, requires_acknowledgement=1).name
		user = make_user(
			"announcement.reader@example.com", [make_desk_role("_Test Attention Announcement Reader")]
		)

		def add_receipt() -> None:
			frappe.get_doc(
				{
					"doctype": RECEIPT,
					"announcement": announcement,
					"user": user,
					"acknowledged_at": now_datetime(),
				}
			).insert(ignore_permissions=True)

		add_receipt()
		with self.assertRaises(frappe.UniqueValidationError):
			add_receipt()
		self.assertEqual(frappe.db.count(RECEIPT, {"announcement": announcement, "user": user}), 1)
