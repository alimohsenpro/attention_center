from unittest.mock import patch

import frappe
from frappe.desk.query_report import run as run_report
from frappe.permissions import can_export
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from attention_center import api
from attention_center.engine import preferences, realtime, registry, runner
from attention_center.sources import announcements
from attention_center.tests.utils import make_desk_role, make_user

KEY = "attention_center.announcements"
SOURCE = "Attention Source"
ANNOUNCEMENT = "Attention Announcement"
RECEIPT = "Attention Announcement Receipt"
REPORT = "Announcement Acknowledgements"
NOT_AVAILABLE = "This announcement is not available to you."


def nudges(publish) -> list[tuple[str | None, dict]]:
	"""(user, message) of every nudge the patched frappe.publish_realtime sent; the user is None for a broadcast."""
	return [
		(call.kwargs.get("user"), call.args[1])
		for call in publish.call_args_list
		if call.args[:1] == (realtime.EVENT,)
	]


def make_user_group(name: str, members: list[str]) -> str:
	frappe.get_doc(
		{"doctype": "User Group", "name": name, "user_group_members": [{"user": user} for user in members]}
	).insert(ignore_permissions=True)
	return name


class AnnouncementTestCase(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# Only this test's announcements exist until the rollback.
		frappe.db.delete(RECEIPT)
		frappe.db.delete(ANNOUNCEMENT)
		registry.sync_sources()
		self.role = make_desk_role("_Test Attention Announcement Role")
		other_role = make_desk_role("_Test Attention Announcement Other Role")
		self.role_holder = make_user("role.holder@example.com", [self.role])
		self.group_member = make_user("group.member@example.com", [other_role])
		self.outsider = make_user("outsider@example.com", [other_role])
		self.website_user = make_user("website.visitor@example.com", [])
		self.manager = make_user("announcement.manager@example.com", ["Attention Manager"])
		self.group = make_user_group("_Test Attention Announcement Team", [self.group_member])
		self.desk_users = (self.role_holder, self.group_member, self.outsider, self.manager)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.cache.delete_value(runner.COUNT_CACHE.format(KEY))

	def announce(self, title: str, **values) -> str:
		"""A published announcement for every desk user unless `values` say otherwise, made by the manager."""
		frappe.set_user(self.manager)
		try:
			return (
				frappe.get_doc(
					{"doctype": ANNOUNCEMENT, "title": title, "published": 1, "all_users": 1, **values}
				)
				.insert()
				.name
			)
		finally:
			frappe.set_user("Administrator")

	def as_user(self, user: str, call, *args, **kwargs):
		frappe.set_user(user)
		try:
			return call(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def source_items(self, user: str) -> list[dict]:
		"""The items of the announcements source as the window gets them for `user`."""
		source = frappe.db.get_value(SOURCE, KEY, list(registry.SOURCE_FIELDS), as_dict=True)
		result = self.as_user(user, runner.run_items, source, user, 0, 50)
		self.assertEqual(result["state"], "ok")
		return result["items"]

	def source_titles(self, user: str) -> list[str]:
		return [item["title"] for item in self.source_items(user)]

	def desk_titles(self, user: str) -> list[str]:
		"""What the user's list of announcements in the desk shows."""
		return self.as_user(user, frappe.get_list, ANNOUNCEMENT, pluck="title", order_by="title asc")

	def may_open(self, user: str, name: str) -> bool:
		return frappe.has_permission(ANNOUNCEMENT, "read", frappe.get_doc(ANNOUNCEMENT, name), user=user)

	def counts(self, user: str, since=None) -> dict:
		frappe.cache.delete_value(runner.COUNT_CACHE.format(KEY))
		source = frappe.db.get_value(SOURCE, KEY, list(registry.SOURCE_FIELDS), as_dict=True)
		result = self.as_user(user, runner.run_count, source, user, since)
		self.assertEqual(result["state"], "ok")
		return result

	def acknowledge(self, user: str, name: str) -> dict:
		return self.as_user(user, api.acknowledge_announcement, name)


class TestAudience(AnnouncementTestCase):
	def test_each_audience_reaches_its_users_and_nobody_else(self):
		cases = (
			("every desk user", {}, {self.role_holder, self.group_member, self.outsider, self.manager}),
			("a role", {"all_users": 0, "roles": [{"role": self.role}]}, {self.role_holder}),
			(
				"a user group",
				{"all_users": 0, "user_groups": [{"user_group": self.group}]},
				{self.group_member},
			),
			(
				"a role or a user group",
				{"all_users": 0, "roles": [{"role": self.role}], "user_groups": [{"user_group": self.group}]},
				{self.role_holder, self.group_member},
			),
		)
		for case, audience, receivers in cases:
			with self.subTest(case):
				name = self.announce(case, **audience)
				for user in self.desk_users:
					with self.subTest(user=user):
						self.assertEqual(case in self.source_titles(user), user in receivers)
				for user in set(self.desk_users) - {self.manager}:
					with self.subTest(user=user):
						self.assertEqual(case in self.desk_titles(user), user in receivers)
						self.assertEqual(self.may_open(user, name), user in receivers)

	def test_a_website_user_receives_nothing(self):
		name = self.announce("For every desk user")

		self.assertEqual(self.as_user(self.website_user, announcements.received, self.website_user), [])
		self.assertFalse(self.may_open(self.website_user, name))
		with self.assertRaises(frappe.PermissionError):
			self.acknowledge(self.website_user, name)

	def test_a_manager_opens_every_announcement_but_receives_only_those_addressed_to_them(self):
		self.announce("For the role", all_users=0, roles=[{"role": self.role}])
		draft = self.announce("Draft", published=0)

		self.assertEqual(self.desk_titles(self.manager), ["Draft", "For the role"])
		self.assertEqual(self.desk_titles(self.outsider), [])
		self.assertTrue(self.may_open(self.manager, draft))
		self.assertEqual(self.source_titles(self.manager), [])
		self.assertEqual(self.counts(self.manager)["count"], 0)

	def test_drafts_and_announcements_outside_their_window_reach_nobody(self):
		now = now_datetime()
		self.announce("Draft", published=0)
		self.announce("Starts tomorrow", valid_from=add_to_date(now, days=1))
		ended = self.announce("Ended an hour ago")
		frappe.db.set_value(
			ANNOUNCEMENT,
			ended,
			{"valid_from": add_to_date(now, days=-2), "valid_to": add_to_date(now, hours=-1)},
		)
		self.announce("Ends tomorrow", valid_to=add_to_date(now, days=1))
		self.announce("Open-ended")

		self.assertEqual(sorted(self.source_titles(self.outsider)), ["Ends tomorrow", "Open-ended"])
		self.assertEqual(self.desk_titles(self.outsider), ["Ends tomorrow", "Open-ended"])
		self.assertFalse(self.may_open(self.outsider, ended))

	def test_a_site_that_withdraws_read_permission_hides_announcements(self):
		self.announce("For every desk user", requires_acknowledgement=1)
		frappe.db.delete("DocPerm", {"parent": ANNOUNCEMENT, "role": "Desk User"})
		# Runs after tearDown: the rollback restores the permission but not the cached meta.
		self.addCleanup(frappe.clear_cache, doctype=ANNOUNCEMENT)
		frappe.clear_cache(doctype=ANNOUNCEMENT)

		self.assertEqual(self.source_titles(self.outsider), [])
		self.assertEqual(self.counts(self.outsider)["count"], 0)


class TestSource(AnnouncementTestCase):
	def test_unacknowledged_announcements_that_ask_for_it_are_action_items(self):
		frappe.db.set_value(SOURCE, {"enabled": 1, "name": ("!=", KEY)}, "enabled", 0)
		registry.clear_visibility_cache()
		self.addCleanup(registry.clear_visibility_cache)
		urgent = self.announce("Urgent, to acknowledge", priority="Urgent", requires_acknowledgement=1)
		self.announce("Immediate, to acknowledge", priority="Immediate", requires_acknowledgement=1)
		self.announce("Immediate, for information", priority="Immediate")

		summary = self.as_user(self.outsider, api.get_summary)
		entry = next(source for source in summary["sources"] if source["key"] == KEY)
		self.assertEqual(
			(entry["kind"], entry["count"], entry["urgent"], entry["immediate"], entry["new_since"]),
			("action", 2, 1, 1, 3),
		)
		self.assertEqual(summary["totals"]["action"], 2)

		self.acknowledge(self.outsider, urgent)
		frappe.cache.delete_value(runner.COUNT_CACHE.format(KEY))
		summary = self.as_user(self.outsider, api.get_summary)
		self.assertEqual((summary["totals"]["action"], summary["totals"]["attention"]), (1, 1))

	def test_items_await_acknowledgement_first_then_go_by_priority_and_newest(self):
		now = now_datetime()
		for hours_ago, title, values in (
			(5, "Old normal, to acknowledge", {"requires_acknowledgement": 1}),
			(4, "Urgent, acknowledged", {"requires_acknowledgement": 1, "priority": "Urgent"}),
			(3, "Normal, for information", {}),
			(2, "Immediate, for information", {"priority": "Immediate"}),
			(1, "New normal, to acknowledge", {"requires_acknowledgement": 1}),
			(0, "Urgent, to acknowledge", {"requires_acknowledgement": 1, "priority": "Urgent"}),
		):
			name = self.announce(title, **values)
			frappe.db.set_value(ANNOUNCEMENT, name, "valid_from", add_to_date(now, hours=-hours_ago))
			if title == "Urgent, acknowledged":
				self.acknowledge(self.outsider, name)

		items = self.source_items(self.outsider)

		self.assertEqual(
			[(item["title"], item["priority"], item["status_label"], item["status_color"]) for item in items],
			[
				("Urgent, to acknowledge", "urgent", "Awaiting acknowledgement", "orange"),
				("New normal, to acknowledge", "normal", "Awaiting acknowledgement", "orange"),
				("Old normal, to acknowledge", "normal", "Awaiting acknowledgement", "orange"),
				("Immediate, for information", "immediate", None, "gray"),
				("Urgent, acknowledged", "urgent", "Acknowledged", "green"),
				("Normal, for information", "normal", None, "gray"),
			],
		)
		self.assertEqual(
			[
				item["title"]
				for item in self.as_user(self.outsider, announcements.get_items, self.outsider, 2, 2)
			],
			["Old normal, to acknowledge", "Immediate, for information"],
		)

	def test_an_item_opens_the_announcement_and_names_its_author(self):
		name = self.announce("Office closed on Friday")

		(item,) = self.source_items(self.outsider)

		self.assertEqual(
			{key: item[key] for key in ("id", "route", "type_label", "from_label", "date", "overdue")},
			{
				"id": name,
				"route": f"/app/attention-announcement/{name}",
				"type_label": "Announcement",
				"from_label": "announcement.manager",
				"date": frappe.db.get_value(ANNOUNCEMENT, name, "valid_from").isoformat(timespec="seconds"),
				"overdue": False,
			},
		)
		self.assertTrue(self.may_open(self.outsider, name))

	def test_the_count_carries_the_latest_announcement_and_those_new_since_the_watermark(self):
		now = now_datetime().replace(microsecond=0)
		older = self.announce("Older")
		frappe.db.set_value(ANNOUNCEMENT, older, "valid_from", add_to_date(now, hours=-3))
		newest = self.announce("Newest")
		frappe.db.set_value(ANNOUNCEMENT, newest, "valid_from", add_to_date(now, hours=-1))

		counts = self.counts(self.outsider, since=add_to_date(now, hours=-2))

		self.assertEqual((counts["count"], counts["new_since"]), (0, 1))
		self.assertEqual(counts["latest"], add_to_date(now, hours=-1).isoformat(timespec="seconds"))
		self.assertEqual(
			self.counts(self.outsider)["new_since"], 2, "no watermark: every announcement is new"
		)


class TestUnseen(AnnouncementTestCase):
	"""What is new to a user: the dots and the toast raised when a desk page loads follow it (§7.4, §7.8)."""

	def setUp(self):
		super().setUp()
		self.now = now_datetime().replace(microsecond=0)

	def published(self, hours_ago: int, title: str, **values) -> str:
		name = self.announce(title, **values)
		frappe.db.set_value(ANNOUNCEMENT, name, "valid_from", add_to_date(self.now, hours=-hours_ago))
		return name

	def unseen(self, user: str) -> tuple[int, dict]:
		"""The source's new_since in the user's summary, and what get_unseen_announcements answers them."""
		frappe.cache.delete_value(runner.COUNT_CACHE.format(KEY))
		summary = self.as_user(user, api.get_summary)
		(entry,) = (source for source in summary["sources"] if source["key"] == KEY)
		return entry["new_since"], self.as_user(user, api.get_unseen_announcements)

	def test_an_announcement_the_user_acknowledged_is_no_longer_new(self):
		with patch.object(preferences, "now_datetime", return_value=add_to_date(self.now, hours=-2)):
			self.as_user(self.outsider, api.mark_seen, KEY)
		self.published(3, "Immediate, before the user looked", priority="Immediate")
		immediate = self.published(
			1, "Immediate, to acknowledge", priority="Immediate", requires_acknowledgement=1
		)
		self.assertEqual(self.unseen(self.outsider), (1, {"count": 1, "immediate": 1}))

		self.acknowledge(self.outsider, immediate)
		self.assertEqual(self.unseen(self.outsider), (0, {"count": 0, "immediate": 0}), "alone")

		self.published(1, "Normal, for information")
		self.assertEqual(
			self.unseen(self.outsider), (1, {"count": 1, "immediate": 0}), "beside a normal one not seen yet"
		)
		self.assertEqual(
			self.unseen(self.role_holder),
			(3, {"count": 3, "immediate": 2}),
			"a user who never looked and acknowledged nothing",
		)

	def test_the_authors_own_announcement_is_not_new_to_them(self):
		self.published(1, "Immediate, for information", priority="Immediate")

		self.assertEqual(self.unseen(self.manager), (0, {"count": 0, "immediate": 0}))
		self.assertEqual(self.unseen(self.outsider), (1, {"count": 1, "immediate": 1}))

	def test_an_announcement_for_others_is_not_counted(self):
		self.published(
			1, "Immediate, for the role", priority="Immediate", all_users=0, roles=[{"role": self.role}]
		)

		self.assertEqual(self.unseen(self.outsider), (0, {"count": 0, "immediate": 0}))
		self.assertEqual(self.unseen(self.role_holder), (1, {"count": 1, "immediate": 1}))


class TestAcknowledgement(AnnouncementTestCase):
	def test_an_acknowledgement_is_stored_once(self):
		name = self.announce("Read the new policy", requires_acknowledgement=1)
		self.assertEqual(self.counts(self.outsider)["count"], 1)

		first = self.acknowledge(self.outsider, name)
		receipt = frappe.db.get_value(
			RECEIPT, {"announcement": name, "user": self.outsider}, "acknowledged_at"
		).isoformat(timespec="seconds")
		self.assertEqual(first, {"announcement": name, "acknowledged_at": receipt})

		with patch.object(announcements, "now_datetime", return_value=add_to_date(now_datetime(), hours=1)):
			self.assertEqual(self.acknowledge(self.outsider, name), first)
		self.assertEqual(frappe.db.count(RECEIPT, {"announcement": name}), 1)
		self.assertEqual(self.counts(self.outsider)["count"], 0)
		self.assertEqual(self.counts(self.role_holder)["count"], 1)

	def test_a_parallel_acknowledgement_keeps_the_receipt_stored_first(self):
		name = self.announce("Read the new policy", requires_acknowledgement=1)
		(before,) = self.as_user(self.outsider, announcements.received, self.outsider, name)
		first = self.acknowledge(self.outsider, name)
		queued_messages = len(frappe.local.message_log)

		# The other request read the announcement before this one stored the receipt.
		with patch.object(announcements, "received", return_value=[before]):
			second = self.acknowledge(self.outsider, name)

		self.assertEqual(second, first)
		self.assertEqual(frappe.db.count(RECEIPT, {"announcement": name}), 1)
		self.assertEqual(len(frappe.local.message_log), queued_messages)

	def test_a_user_outside_the_audience_cannot_acknowledge(self):
		cases = (
			("outside the audience", self.announce("For the role", all_users=0, roles=[{"role": self.role}])),
			("a draft", self.announce("Draft", published=0, requires_acknowledgement=1)),
			("an announcement that does not exist", "no-such-announcement"),
		)
		for case, name in cases:
			with self.subTest(case), self.assertRaises(frappe.PermissionError) as raised:
				self.acknowledge(self.outsider, name)
			self.assertEqual(str(raised.exception), NOT_AVAILABLE)
		self.assertFalse(frappe.db.exists(RECEIPT, {"user": self.outsider}))

	def test_an_announcement_that_does_not_ask_for_it_cannot_be_acknowledged(self):
		name = self.announce("For information")

		with self.assertRaises(frappe.ValidationError):
			self.acknowledge(self.outsider, name)
		self.assertFalse(frappe.db.exists(RECEIPT, {"announcement": name}))

	def test_acknowledging_nudges_the_users_other_tabs_after_the_commit(self):
		with patch("frappe.publish_realtime") as publish:
			name = self.announce("Read the new policy", requires_acknowledgement=1)
			frappe.db.after_commit.run()
			publish.reset_mock()
			frappe.set_user(self.outsider)
			api.acknowledge_announcement(name)
			frappe.db.after_commit.run()

		self.assertEqual(nudges(publish), [(self.outsider, {"sources": [KEY], "actor": self.outsider})])

	def test_publishing_an_announcement_is_broadcast(self):
		with patch("frappe.publish_realtime") as publish:
			frappe.db.after_commit.run()
			publish.reset_mock()
			self.announce("Office closed on Friday")
			frappe.db.after_commit.run()

		self.assertEqual(nudges(publish), [(None, {"sources": [KEY], "broadcast": True})])


class TestReceipts(AnnouncementTestCase):
	def test_a_manager_sees_who_acknowledged_and_who_has_not(self):
		name = self.announce(
			"Read the new policy",
			requires_acknowledgement=1,
			all_users=0,
			roles=[{"role": self.role}],
			user_groups=[{"user_group": self.group}],
		)
		second_holder = make_user("second.holder@example.com", [self.role])
		frappe.db.set_value("User", second_holder, "enabled", 0)
		acknowledged_at = self.acknowledge(self.group_member, name)["acknowledged_at"]

		receipts = self.as_user(self.manager, api.get_announcement_receipts, name)

		self.assertEqual(
			receipts,
			{
				"acknowledged": [
					{
						"user": self.group_member,
						"full_name": "group.member",
						"acknowledged_at": acknowledged_at,
					}
				],
				"pending": [{"user": self.role_holder, "full_name": "role.holder"}],
			},
		)

	def test_an_announcement_for_every_desk_user_awaits_every_enabled_desk_user(self):
		name = self.announce("Read the new policy", requires_acknowledgement=1)

		pending = {
			row["user"] for row in self.as_user(self.manager, api.get_announcement_receipts, name)["pending"]
		}

		self.assertLessEqual(set(self.desk_users), pending)
		self.assertNotIn(self.website_user, pending)

	def test_receipts_are_visible_to_managers_only(self):
		name = self.announce("Read the new policy", requires_acknowledgement=1)
		self.acknowledge(self.role_holder, name)

		for user in (self.role_holder, self.outsider):
			with self.subTest(user=user):
				with self.assertRaises(frappe.PermissionError):
					self.as_user(user, api.get_announcement_receipts, name)
				with self.assertRaises(frappe.PermissionError):
					self.as_user(user, frappe.get_list, RECEIPT, fields=["user"])
				receipt = frappe.get_last_doc(RECEIPT, filters={"announcement": name})
				self.assertFalse(frappe.has_permission(RECEIPT, "read", receipt, user=user))

		self.assertEqual(
			self.as_user(
				self.manager, frappe.get_list, RECEIPT, filters={"announcement": name}, pluck="user"
			),
			[self.role_holder],
		)

	def test_the_receipts_of_an_announcement_that_does_not_exist_are_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			self.as_user(self.manager, api.get_announcement_receipts, "no-such-announcement")


class TestWindow(AnnouncementTestCase):
	def hide_the_source(self):
		frappe.db.set_value(SOURCE, KEY, "enabled", 0)
		registry.clear_visibility_cache()
		self.addCleanup(registry.clear_visibility_cache)

	def test_the_all_tab_gets_only_the_announcements_awaiting_acknowledgement(self):
		now = now_datetime()
		for hours_ago, title, values in (
			(3, "Old normal, to acknowledge", {"requires_acknowledgement": 1}),
			(2, "Immediate, for information", {"priority": "Immediate"}),
			(1, "Urgent, acknowledged", {"requires_acknowledgement": 1, "priority": "Urgent"}),
			(0, "New normal, to acknowledge", {"requires_acknowledgement": 1}),
		):
			name = self.announce(title, **values)
			frappe.db.set_value(ANNOUNCEMENT, name, "valid_from", add_to_date(now, hours=-hours_ago))
			if title == "Urgent, acknowledged":
				self.acknowledge(self.outsider, name)
		self.announce("For the role", requires_acknowledgement=1, all_users=0, roles=[{"role": self.role}])

		first = self.as_user(self.outsider, api.get_announcements_to_acknowledge, page_length=1)
		second = self.as_user(self.outsider, api.get_announcements_to_acknowledge, start=1, page_length=1)

		self.assertEqual(
			[
				(page["state"], [item["title"] for item in page["items"]], page["has_more"])
				for page in (first, second)
			],
			[("ok", ["New normal, to acknowledge"], True), ("ok", ["Old normal, to acknowledge"], False)],
		)
		self.assertEqual(first["items"][0]["status_label"], "Awaiting acknowledgement")
		self.assertEqual(
			[
				item["title"]
				for item in self.as_user(self.role_holder, api.get_announcements_to_acknowledge)["items"]
			],
			[
				"Urgent, acknowledged",
				"For the role",
				"New normal, to acknowledge",
				"Old normal, to acknowledge",
			],
		)

	def test_the_detail_shows_the_sanitised_body_and_the_users_acknowledgement(self):
		name = self.announce(
			"Read the new policy",
			priority="Urgent",
			requires_acknowledgement=1,
			body="<p>The policy <b>changes</b> today.</p><script>alert(1)</script>",
		)
		# A body written past the controller is sanitised when it is read.
		frappe.db.set_value(
			ANNOUNCEMENT,
			name,
			"body",
			'<p>The policy <b>changes</b> today.</p><img src="x" onerror="alert(1)">',
		)
		values = frappe.db.get_value(ANNOUNCEMENT, name, ["valid_from"], as_dict=True)

		detail = self.as_user(self.outsider, api.get_announcement, name)

		self.assertEqual(
			{key: value for key, value in detail.items() if key != "body"},
			{
				"name": name,
				"title": "Read the new policy",
				"priority": "urgent",
				"from_label": "announcement.manager",
				"date": values.valid_from.isoformat(timespec="seconds"),
				"valid_to": None,
				"requires_acknowledgement": True,
				"acknowledged_at": None,
			},
		)
		self.assertIn("<b>changes</b>", detail["body"])
		self.assertNotIn("onerror", detail["body"])
		self.assertNotIn("<script", frappe.db.get_value(ANNOUNCEMENT, name, "body") or "")

		acknowledged_at = self.acknowledge(self.outsider, name)["acknowledged_at"]
		self.assertEqual(
			self.as_user(self.outsider, api.get_announcement, name)["acknowledged_at"], acknowledged_at
		)
		self.assertIsNone(self.as_user(self.role_holder, api.get_announcement, name)["acknowledged_at"])

	def test_the_detail_is_refused_for_an_announcement_the_user_does_not_receive(self):
		cases = (
			("outside the audience", self.announce("For the role", all_users=0, roles=[{"role": self.role}])),
			("a draft", self.announce("Draft", published=0)),
			("an announcement that does not exist", "no-such-announcement"),
		)
		for case, name in cases:
			with self.subTest(case), self.assertRaises(frappe.PermissionError) as raised:
				self.as_user(self.outsider, api.get_announcement, name)
			self.assertEqual(str(raised.exception), NOT_AVAILABLE)
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.manager, api.get_announcement, cases[0][1])

	def test_the_endpoints_are_refused_while_the_source_is_hidden(self):
		name = self.announce("Read the new policy", requires_acknowledgement=1)
		self.hide_the_source()

		for endpoint, arguments in (
			(api.get_announcements_to_acknowledge, ()),
			(api.get_announcement, (name,)),
			(api.get_unseen_announcements, ()),
		):
			with self.subTest(endpoint=endpoint.__name__), self.assertRaises(frappe.PermissionError):
				self.as_user(self.outsider, endpoint, *arguments)


class TestReceiptReport(AnnouncementTestCase):
	def run_report(self, user: str, name: str) -> dict:
		return self.as_user(user, run_report, REPORT, filters={"announcement": name})

	def test_a_manager_sees_who_acknowledged_and_who_has_not_with_the_totals(self):
		name = self.announce(
			"Read the new policy",
			requires_acknowledgement=1,
			all_users=0,
			roles=[{"role": self.role}],
			user_groups=[{"user_group": self.group}],
		)
		acknowledged_at = self.acknowledge(self.group_member, name)["acknowledged_at"]

		report = self.run_report(self.manager, name)

		self.assertEqual(
			[
				(
					row["user"],
					row["status"],
					row.get("acknowledged_at") and row["acknowledged_at"].isoformat(),
				)
				for row in report["result"]
			],
			[
				(self.group_member, "Acknowledged", acknowledged_at),
				(self.role_holder, "Awaiting acknowledgement", None),
			],
		)
		self.assertEqual(
			[(entry["label"], entry["value"]) for entry in report["report_summary"]],
			[("Acknowledged", 1), ("Awaiting acknowledgement", 1)],
		)
		self.assertEqual(
			[column["fieldname"] for column in report["columns"]],
			["full_name", "user", "status", "acknowledged_at"],
		)

	def test_the_report_and_its_export_are_refused_to_other_users(self):
		name = self.announce("Read the new policy", requires_acknowledgement=1)
		self.acknowledge(self.role_holder, name)
		execute = frappe.get_attr(
			"attention_center.attention_center.report.announcement_acknowledgements"
			".announcement_acknowledgements.execute"
		)

		for user in (self.role_holder, self.outsider):
			with self.subTest(user=user):
				with self.assertRaises(frappe.PermissionError):
					self.run_report(user, name)
				with self.assertRaises(frappe.PermissionError):
					self.as_user(user, execute, frappe._dict(announcement=name))
				self.assertFalse(self.as_user(user, can_export, RECEIPT))
		self.assertTrue(self.as_user(self.manager, can_export, RECEIPT))

	def test_an_announcement_that_asks_for_no_acknowledgement_lists_nobody(self):
		name = self.announce("For information")

		report = self.run_report(self.manager, name)

		self.assertEqual(report["result"], [])
		self.assertEqual(report["message"], "This announcement does not ask for an acknowledgement.")
