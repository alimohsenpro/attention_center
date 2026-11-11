from datetime import date, datetime, time, timedelta

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, now_datetime, today

from attention_center.engine import registry, runner
from attention_center.sources import builtin, events, reminders
from attention_center.tests.utils import make_desk_role, make_user

SOURCE = "Attention Source"
APPROVALS = "attention_center.approvals"
ASSIGNMENTS = "attention_center.assignments"
NOTIFICATIONS = "attention_center.notifications"
ANNOUNCEMENTS = "attention_center.announcements"
EVENTS = "attention_center.events"
REMINDERS = "attention_center.reminders"
BUILT_IN = (APPROVALS, ASSIGNMENTS, NOTIFICATIONS, ANNOUNCEMENTS, EVENTS, REMINDERS)


def add_note(title: str) -> str:
	return frappe.get_doc({"doctype": "Note", "title": title}).insert(ignore_permissions=True).name


def creation(doctype: str, name: str) -> str:
	return frappe.db.get_value(doctype, name, "creation").isoformat(timespec="seconds")


def at(day: date, hour: int, minute: int = 0) -> datetime:
	return datetime.combine(day, time(hour, minute))


class BuiltinSourceTestCase(FrappeTestCase):
	key: str

	def setUp(self):
		registry.sync_sources()
		self.source = frappe.db.get_value(SOURCE, self.key, list(registry.SOURCE_FIELDS), as_dict=True)
		role = make_desk_role("_Test Attention Desk User")
		self.user = make_user("attention.user@example.com", [role])
		self.other_user = make_user("other.user@example.com", [role])
		self.sender = make_user("sender@example.com", [role])

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.cache.delete_value(runner.COUNT_CACHE.format(self.key))

	def summary(self, user: str) -> dict:
		frappe.cache.delete_value(runner.COUNT_CACHE.format(self.key))
		frappe.set_user(user)
		try:
			result = runner.run_count(self.source, user)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(result["state"], "ok")
		return result

	def items(self, user: str) -> list[dict]:
		frappe.set_user(user)
		try:
			result = runner.run_items(self.source, user, 0, 50)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(result["state"], "ok")
		return result["items"]


class TestRegistration(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		registry.clear_visibility_cache()

	def test_this_apps_hooks_declare_the_built_in_sources(self):
		declared = {
			source["key"]: source["app"]
			for source in registry.load_hook_sources()
			if source["app"] == "attention_center"
		}

		self.assertEqual(declared, dict.fromkeys(BUILT_IN, "attention_center"))
		self.assertEqual([source["key"] for source in builtin.SOURCES], list(BUILT_IN))

	def test_the_sync_stores_them_as_enabled_system_sources_every_desk_user_sees(self):
		frappe.db.delete(SOURCE, {"name": ("in", BUILT_IN)})
		user = make_user("desk.user@example.com", [make_desk_role("_Test Attention Desk User")])

		registry.sync_sources()

		self.assertEqual(
			list(
				frappe.get_all(
					SOURCE,
					filters={"name": ("in", BUILT_IN)},
					fields=["name", "kind", "source_type", "enabled", "is_system"],
					order_by="name",
					as_list=True,
				)
			),
			[
				(ANNOUNCEMENTS, "Action", "Python", 1, 1),
				(APPROVALS, "Action", "Python", 1, 1),
				(ASSIGNMENTS, "Action", "DocType Query", 1, 1),
				(EVENTS, "Info", "Python", 1, 1),
				(NOTIFICATIONS, "Info", "DocType Query", 1, 1),
				(REMINDERS, "Info", "Python", 1, 1),
			],
		)
		visible = [source.key for source in registry.get_visible_sources(user)]
		self.assertEqual([key for key in visible if key.startswith("attention_center.")], list(BUILT_IN))


class TestAssignments(BuiltinSourceTestCase):
	key = ASSIGNMENTS

	def add_todo(self, description: str, allocated_to: str | None = None, **values) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "ToDo",
					"description": description,
					"allocated_to": allocated_to or self.user,
					**values,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_an_item_opens_the_referenced_document_and_carries_the_mapped_fields(self):
		note = add_note("Quarterly report")
		yesterday = add_days(today(), -1)
		todo = self.add_todo(
			"<p>Check the <b>quarterly</b> report</p>",
			assigned_by=self.sender,
			priority="High",
			date=yesterday,
			reference_type="Note",
			reference_name=note,
		)

		self.assertEqual(
			self.items(self.user),
			[
				{
					"id": todo,
					"title": "Check the quarterly report",
					"route": f"/app/note/{note}",
					"reference_doctype": "Note",
					"reference_name": note,
					"type_label": None,
					"from_label": "sender",
					"date": creation("ToDo", todo),
					"priority": "urgent",
					"due": yesterday,
					"overdue": True,
					"status_label": None,
					"status_color": "gray",
				}
			],
		)

	def test_an_assignment_without_a_reference_opens_the_todo(self):
		todo = self.add_todo("Call the supplier")

		self.assertEqual([item["route"] for item in self.items(self.user)], [f"/app/todo/{todo}"])

	def test_high_maps_to_urgent_and_the_todo_date_is_the_due_date(self):
		self.add_todo("High, due yesterday", priority="High", date=add_days(today(), -1))
		self.add_todo("High, due today", priority="High", date=today())
		self.add_todo("Medium, due yesterday", priority="Medium", date=add_days(today(), -1))
		self.add_todo("Low, no date", priority="Low")

		summary = self.summary(self.user)
		items = {item["title"]: (item["priority"], item["overdue"]) for item in self.items(self.user)}

		self.assertEqual((summary["count"], summary["urgent"], summary["overdue"]), (4, 2, 2))
		self.assertEqual(
			items,
			{
				"High, due yesterday": ("urgent", True),
				"High, due today": ("urgent", False),
				"Medium, due yesterday": ("normal", True),
				"Low, no date": ("normal", False),
			},
		)

	def test_closed_assignments_and_other_users_rows_are_invisible(self):
		self.add_todo("Mine")
		self.add_todo("Mine, closed", status="Closed")
		self.add_todo("Mine, cancelled", status="Cancelled")
		self.add_todo("Theirs", allocated_to=self.other_user)

		self.assertEqual([item["title"] for item in self.items(self.user)], ["Mine"])
		self.assertEqual(self.summary(self.user)["count"], 1)
		self.assertEqual([item["title"] for item in self.items(self.other_user)], ["Theirs"])
		self.assertEqual(self.summary(self.other_user)["count"], 1)


class TestNotifications(BuiltinSourceTestCase):
	key = NOTIFICATIONS

	def add_log(self, subject: str, for_user: str | None = None, **values) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"subject": subject,
					"for_user": for_user or self.user,
					**values,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_an_item_opens_the_referenced_document_and_carries_the_mapped_fields(self):
		note = add_note("Budget")
		log = self.add_log(
			"<b>Budget</b> was shared with you",
			from_user=self.sender,
			document_type="Note",
			document_name=note,
		)

		self.assertEqual(
			self.items(self.user),
			[
				{
					"id": log,
					"title": "Budget was shared with you",
					"route": f"/app/note/{note}",
					"reference_doctype": "Note",
					"reference_name": note,
					"type_label": None,
					"from_label": "sender",
					"date": creation("Notification Log", log),
					"priority": "normal",
					"due": None,
					"overdue": False,
					"status_label": None,
					"status_color": "gray",
				}
			],
		)

	def test_the_route_is_the_link_then_the_reference_then_the_log(self):
		note = add_note("Budget")
		reference = {"document_type": "Note", "document_name": note}
		desk_link = self.add_log("Desk link", link="/app/todo?status=Open", **reference)
		outside_link = self.add_log("Link outside the desk", link="https://example.com/report", **reference)
		reference_only = self.add_log("Reference only", **reference)
		half_reference = self.add_log("Document type only", document_type="Note")
		bare = self.add_log("No link or reference")

		items = self.items(self.user)
		routes = {item["id"]: item["route"] for item in items}
		documents = {item["id"]: (item["reference_doctype"], item["reference_name"]) for item in items}

		# A link keeps the item about its document, which a reminder names.
		self.assertEqual(documents[desk_link], ("Note", note))
		self.assertEqual(
			routes,
			{
				desk_link: "/app/todo?status=Open",
				outside_link: f"/app/note/{note}",
				reference_only: f"/app/note/{note}",
				half_reference: f"/app/notification-log/{half_reference}",
				bare: f"/app/notification-log/{bare}",
			},
		)

	def test_read_logs_and_other_users_logs_are_invisible(self):
		self.add_log("Unread")
		self.add_log("Read", read=1)
		self.add_log("For someone else", for_user=self.other_user)

		self.assertEqual([item["title"] for item in self.items(self.user)], ["Unread"])
		self.assertEqual(self.summary(self.user)["count"], 1)
		self.assertEqual([item["title"] for item in self.items(self.other_user)], ["For someone else"])
		self.assertEqual(self.summary(self.other_user)["count"], 1)


class TestEvents(BuiltinSourceTestCase):
	key = EVENTS

	def setUp(self):
		super().setUp()
		self.today = getdate()

	def add_event(self, subject: str, owner: str | None = None, **values) -> str:
		frappe.set_user(owner or self.user)
		try:
			event = frappe.get_doc(
				{"doctype": "Event", "subject": subject, "starts_on": at(self.today, 10), **values}
			).insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")
		return event.name

	def titles(self, user: str) -> list[str]:
		return [item["title"] for item in self.items(user)]

	def test_todays_events_come_in_the_order_of_the_day_and_open_the_event(self):
		yesterday, tomorrow = add_days(self.today, -1), add_days(self.today, 1)
		standup = self.add_event("Standup", starts_on=at(self.today, 10), event_category="Meeting")
		self.add_event("Planning", starts_on=at(self.today, 9), ends_on=at(self.today, 9, 30))
		self.add_event("Holiday", starts_on=at(self.today, 0), all_day=1)
		self.add_event("Workshop", starts_on=at(yesterday, 9), ends_on=at(tomorrow, 17))

		items = self.items(self.user)

		self.assertEqual([item["title"] for item in items], ["Holiday", "Workshop", "Planning", "Standup"])
		self.assertEqual(
			items[3],
			{
				"id": standup,
				"title": "Standup",
				"route": f"/app/event/{standup}",
				"reference_doctype": "Event",
				"reference_name": standup,
				"type_label": "Meeting",
				"from_label": "attention.user",
				"date": at(self.today, 10).isoformat(),
				"priority": "normal",
				"due": None,
				"overdue": False,
				"status_label": None,
				"status_color": "gray",
			},
		)
		# An all-day event has no time to show.
		self.assertEqual((items[0]["date"], items[0]["status_label"]), (None, "All day"))

	def test_events_of_other_days_and_events_no_longer_open_are_left_out(self):
		yesterday, tomorrow = add_days(self.today, -1), add_days(self.today, 1)
		self.add_event("Today")
		self.add_event("Yesterday", starts_on=at(yesterday, 10))
		self.add_event("Ended yesterday", starts_on=at(yesterday, 9), ends_on=at(yesterday, 17))
		self.add_event("Tomorrow", starts_on=at(tomorrow, 10))
		self.add_event("Cancelled", status="Cancelled")
		self.add_event("Closed", status="Closed")

		self.assertEqual(self.titles(self.user), ["Today"])
		self.assertEqual(self.summary(self.user)["count"], 1)

	def test_a_repeating_event_shows_on_the_days_it_repeats_until_it_ends(self):
		last_week = add_days(self.today, -7)
		other_weekday = events.WEEKDAYS[add_days(self.today, 1).weekday()]
		today_weekday = events.WEEKDAYS[self.today.weekday()]
		repeat = {"repeat_this_event": 1, "starts_on": at(last_week, 8)}
		self.add_event("Daily", repeat_on="Daily", **repeat)
		self.add_event("Weekly today", repeat_on="Weekly", **{today_weekday: 1}, **repeat)
		self.add_event("Weekly another day", repeat_on="Weekly", **{other_weekday: 1}, **repeat)
		self.add_event("Daily, ended", repeat_on="Daily", repeat_till=add_days(self.today, -1), **repeat)

		items = self.items(self.user)

		self.assertEqual(sorted(item["title"] for item in items), ["Daily", "Weekly today"])
		# The occurrence of today is shown at the time of the series.
		self.assertEqual({item["date"] for item in items}, {at(self.today, 8).isoformat()})

	def test_occurrences_follow_frappes_calendar(self):
		def event(starts_on: datetime, **values) -> frappe._dict:
			return frappe._dict({"starts_on": starts_on, "ends_on": None, "repeat_this_event": 0, **values})

		def repeating(repeat_on: str, starts_on: datetime, **values) -> frappe._dict:
			return event(starts_on, repeat_this_event=1, repeat_on=repeat_on, **values)

		monday = datetime(2026, 3, 2, 9)
		cases = [
			("one-off, its day", event(datetime(2026, 3, 10, 10)), date(2026, 3, 10), True),
			("one-off, the next day", event(datetime(2026, 3, 10, 10)), date(2026, 3, 11), False),
			(
				"over several days, a day inside",
				event(datetime(2026, 3, 9, 22), ends_on=datetime(2026, 3, 11, 2)),
				date(2026, 3, 10),
				True,
			),
			("daily, after its start", repeating("Daily", monday), date(2026, 3, 10), True),
			("daily, before its start", repeating("Daily", monday), date(2026, 3, 1), False),
			(
				"daily, after repeat_till",
				repeating("Daily", monday, repeat_till=date(2026, 3, 5)),
				date(2026, 3, 10),
				False,
			),
			("weekly, a chosen weekday", repeating("Weekly", monday, monday=1), date(2026, 3, 9), True),
			("weekly, another weekday", repeating("Weekly", monday, monday=1), date(2026, 3, 10), False),
			(
				"monthly, a short month",
				repeating("Monthly", datetime(2026, 1, 31, 9)),
				date(2026, 2, 28),
				True,
			),
			(
				"monthly, a long month",
				repeating("Monthly", datetime(2026, 1, 31, 9)),
				date(2026, 3, 31),
				True,
			),
			(
				"monthly, another day",
				repeating("Monthly", datetime(2026, 1, 31, 9)),
				date(2026, 3, 28),
				False,
			),
			("yearly, a common year", repeating("Yearly", datetime(2024, 2, 29, 9)), date(2026, 2, 28), True),
			("yearly, another day", repeating("Yearly", datetime(2024, 2, 29, 9)), date(2026, 3, 1), False),
		]
		for name, case, day, expected in cases:
			with self.subTest(name):
				self.assertEqual(events.occurs_on(case, day), expected)

	def test_others_private_events_are_invisible_while_public_ones_and_participations_show(self):
		contact = frappe.get_doc({"doctype": "Contact", "first_name": "Sample"}).insert(
			ignore_permissions=True
		)
		self.add_event("Mine")
		self.add_event("Their private event", owner=self.other_user)
		self.add_event("Their public event", owner=self.other_user, event_type="Public")
		self.add_event(
			"I take part",
			owner=self.other_user,
			event_participants=[
				{"reference_doctype": "Contact", "reference_docname": contact.name, "email": self.user}
			],
		)

		self.assertEqual(sorted(self.titles(self.user)), ["I take part", "Mine", "Their public event"])
		self.assertEqual(self.summary(self.user)["count"], 3)
		self.assertEqual(
			sorted(self.titles(self.other_user)),
			["I take part", "Their private event", "Their public event"],
		)

	def test_an_event_is_new_from_the_start_of_the_day_or_from_its_last_change(self):
		midnight = at(self.today, 0)
		older = self.add_event("Set up last week")
		frappe.db.set_value("Event", older, "modified", midnight - timedelta(days=7), update_modified=False)
		fresh = self.add_event("Added now")
		changed_at = frappe.db.get_value("Event", fresh, "modified")

		before_today = self.count_since(midnight - timedelta(hours=1))
		this_morning = self.count_since(midnight + timedelta(seconds=1))

		self.assertEqual((before_today["new_since"], this_morning["new_since"]), (2, 1))
		self.assertEqual(this_morning["latest"], changed_at.isoformat(timespec="seconds"))

	def count_since(self, since: datetime) -> dict:
		frappe.cache.delete_value(runner.COUNT_CACHE.format(self.key))
		frappe.set_user(self.user)
		try:
			return runner.run_count(self.source, self.user, since)
		finally:
			frappe.set_user("Administrator")

	def test_a_change_nudges_whom_todays_list_concerns(self):
		contact = frappe.get_doc({"doctype": "Contact", "first_name": "Sample"}).insert(
			ignore_permissions=True
		)
		website_user = make_user("website.user@example.com", [])
		participant = {
			"reference_doctype": "Contact",
			"reference_docname": contact.name,
			"email": self.other_user,
		}
		private = frappe.get_doc("Event", self.add_event("Private", event_participants=[participant]))
		tomorrow = frappe.get_doc(
			"Event", self.add_event("Tomorrow", starts_on=at(add_days(self.today, 1), 10))
		)
		public = frappe.get_doc("Event", self.add_event("Public", event_type="Public"))

		self.assertEqual(sorted(events.get_recipients(private)), sorted([self.other_user, self.user]))
		self.assertEqual(events.get_recipients(tomorrow), [])
		everyone = events.get_recipients(public)
		self.assertTrue({self.user, self.other_user, self.sender} <= set(everyone))
		self.assertNotIn(website_user, everyone)

		# Moved off today, it still leaves the list it was on.
		private.starts_on = at(add_days(self.today, 1), 10)
		private.save(ignore_permissions=True)
		self.assertEqual(sorted(set(events.get_recipients(private))), sorted([self.other_user, self.user]))


class TestDueReminders(BuiltinSourceTestCase):
	key = REMINDERS

	def add_reminder(
		self, description: str, remind_at: datetime, user: str | None = None, doctype=None, name=None
	) -> str:
		frappe.set_user(user or self.user)
		try:
			reminder = reminders.remind(now_datetime() + timedelta(hours=1), description, doctype, name)
		finally:
			frappe.set_user("Administrator")
		# Frappe refuses a reminder in the past: it is moved there, as time would.
		frappe.db.set_value("Reminder", reminder.name, "remind_at", remind_at)
		return reminder.name

	def test_due_reminders_come_latest_first_and_open_their_document(self):
		now = now_datetime().replace(microsecond=0)
		note = (
			frappe.get_doc({"doctype": "Note", "title": "Budget", "public": 1})
			.insert(ignore_permissions=True)
			.name
		)
		about_note = self.add_reminder("Read the budget", now - timedelta(hours=2), doctype="Note", name=note)
		bare = self.add_reminder("Call back", now - timedelta(minutes=10))

		items = self.items(self.user)

		self.assertEqual([item["id"] for item in items], [bare, about_note])
		self.assertEqual(
			items[1],
			{
				"id": about_note,
				"title": "Read the budget",
				"route": f"/app/note/{note}",
				"reference_doctype": "Note",
				"reference_name": note,
				"type_label": "Note",
				"from_label": None,
				"date": (now - timedelta(hours=2)).isoformat(),
				"priority": "normal",
				"due": None,
				"overdue": False,
				"status_label": None,
				"status_color": "gray",
			},
		)
		# Without a document a reminder opens itself.
		self.assertEqual(items[0]["route"], f"/app/reminder/{bare}")

	def test_reminders_not_yet_due_due_over_a_day_ago_or_of_others_are_left_out(self):
		now = now_datetime()
		self.add_reminder("Due", now - timedelta(minutes=5))
		self.add_reminder("Later", now + timedelta(hours=2))
		self.add_reminder("Two days ago", now - timedelta(days=2))
		self.add_reminder("Theirs", now - timedelta(minutes=5), user=self.other_user)

		self.assertEqual([item["title"] for item in self.items(self.user)], ["Due"])
		self.assertEqual(self.summary(self.user)["count"], 1)
		self.assertEqual([item["title"] for item in self.items(self.other_user)], ["Theirs"])

	def test_a_reminder_is_new_once_it_falls_due_after_the_user_looked(self):
		now = now_datetime().replace(microsecond=0)
		self.add_reminder("This morning", now - timedelta(hours=3))
		self.add_reminder("Just now", now - timedelta(minutes=1))

		frappe.set_user(self.user)
		counts = reminders.get_count(self.user, since=now - timedelta(hours=1))
		frappe.set_user("Administrator")

		self.assertEqual((counts["count"], counts["new_since"]), (2, 1))
		self.assertEqual(counts["latest"], now - timedelta(minutes=1))
		self.assertEqual(self.summary(self.user)["new_since"], 2)

	def test_a_change_of_a_reminder_nudges_its_user(self):
		reminder = frappe.get_doc("Reminder", self.add_reminder("Due", now_datetime()))

		self.assertEqual(reminders.get_recipients(reminder), [self.user])
