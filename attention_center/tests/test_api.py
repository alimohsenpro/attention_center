import hashlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.exceptions import FrappeTypeError
from frappe.handler import is_valid_http_method
from frappe.permissions import add_permission
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_system_timezone, now_datetime, today

from attention_center import api, boot
from attention_center.engine import registry, runner
from attention_center.tests.utils import make_desk_role, make_user

SOURCE = "Attention Source"
SETTINGS = "Attention Center Settings"
PREFERENCE = "Attention User Preference"
TODOS = "test_app.todos"
FEED = "test_app.feed"
NUMBERS = "test_app.numbers"
BROKEN = "test_app.broken"
RESTRICTED = "test_app.restricted"
ROLE_PROFILES = "test_app.role_profiles"
KEYS = (TODOS, FEED, NUMBERS, BROKEN, RESTRICTED, ROLE_PROFILES)
API = "attention_center.api"
ENDPOINTS = {
	"get_summary": {},
	"get_items": {"source": TODOS},
	"mark_seen": {"source": TODOS},
	"get_preferences": {},
	"set_preferences": {"prefs": {"volume": 10}},
	"note_auto_opened": {},
	"test_source": {"source": TODOS},
}
# The settings' defaults, which ApiTestCase sets.
DEFAULT_PREFERENCES = {
	"display_mode": "Dialog",
	"auto_open_on_login": True,
	"sound_scope": "Action Items",
	"tone": "chime",
	"volume": 60,
	"dnd_until": None,
	"launcher_collapsed": False,
}


def feed_count(user: str, since: datetime | None = None) -> dict:
	return {"count": 3, "new_since": 3 if since is None else 1}


def no_items(user: str, start: int, page_length: int) -> list[dict]:
	return []


def no_count(user: str) -> int:
	return 0


def numbered_items(user: str, start: int, page_length: int) -> list[dict]:
	"""As many items as asked for: the source never runs out."""
	return [
		{"id": str(number), "title": f"Item {number}", "route": f"/app/todo/{number}"}
		for number in range(start, start + page_length)
	]


def count_that_raises(user: str) -> int:
	raise ValueError("broken source")


def items_that_raise(user: str, start: int, page_length: int) -> list[dict]:
	raise ValueError("broken source")


def add_python_source(key: str, kind: str, get_count: str, get_items: str, sort_order: int) -> None:
	doc = frappe.get_doc(
		{
			"doctype": SOURCE,
			"key": key,
			"label": key,
			"kind": kind,
			"source_type": "Python",
			"sort_order": sort_order,
			"is_system": 1,
			"app": "attention_center",
			"get_count": f"{__name__}.{get_count}",
			"get_items": f"{__name__}.{get_items}",
		}
	)
	# The hook sync is the only way to declare a python source; this stands in for it.
	doc.flags.from_hooks = True
	doc.insert()


def add_todo_source(key: str, sort_order: int, roles: tuple[str, ...] = ()) -> None:
	frappe.get_doc(
		{
			"doctype": SOURCE,
			"key": key,
			"label": "Open tasks",
			"kind": "Action",
			"source_type": "DocType Query",
			"sort_order": sort_order,
			"reference_doctype": "ToDo",
			"title_field": "description",
			"date_field": "creation",
			"priority_field": "priority",
			"due_field": "date",
			"priority_map_json": json.dumps({"High": "urgent"}),
			"filters_json": json.dumps([["status", "=", "Open"], ["allocated_to", "=", "{user}"]]),
			"list_route": "/app/todo",
			"roles": [{"role": role} for role in roles],
		}
	).insert()


def add_todo(user: str, description: str, **values) -> str:
	return (
		frappe.get_doc({"doctype": "ToDo", "description": description, "allocated_to": user, **values})
		.insert(ignore_permissions=True)
		.name
	)


def update_settings(**values) -> None:
	settings = frappe.get_single(SETTINGS)
	settings.update(values)
	settings.save()


def stored_preference(user: str) -> frappe._dict | None:
	return frappe.db.get_value(
		PREFERENCE, user, ["volume", "display_mode", "watermarks", "last_auto_open_sid"], as_dict=True
	)


class ApiTestCase(FrappeTestCase):
	"""Every test sees only its own sources: the built-in ones would add their counts to the totals."""

	def setUp(self):
		frappe.set_user("Administrator")
		role = make_desk_role("_Test Attention API Role")
		self.other_role = make_desk_role("_Test Attention API Other Role")
		self.user = make_user("api.user@example.com", [role])
		self.other_user = make_user("api.other@example.com", [role])
		self.website_user = make_user("api.website@example.com", [])
		self.manager = make_user("api.manager@example.com", [role, "Attention Manager"])

		update_settings(
			enabled=1,
			page_size=10,
			default_display_mode="Dialog",
			default_auto_open_on_login=1,
			default_sound_scope="Action Items",
			default_tone="chime",
			default_volume=60,
		)
		frappe.db.set_value(SOURCE, {"enabled": 1}, "enabled", 0)
		add_todo_source(TODOS, sort_order=1)
		add_python_source(FEED, "Info", "feed_count", "no_items", sort_order=2)
		add_python_source(NUMBERS, "Action", "no_count", "numbered_items", sort_order=3)
		add_todo_source(RESTRICTED, sort_order=4, roles=(self.other_role,))
		registry.clear_visibility_cache()
		frappe.set_user(self.user)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		registry.clear_visibility_cache()
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		for key in KEYS:
			frappe.cache.delete_value(runner.COUNT_CACHE.format(key))

	def source_entry(self, key: str) -> dict:
		return next(source for source in api.get_summary()["sources"] if source["key"] == key)

	def forget_counts(self, key: str) -> None:
		"""What a nudge does when a document of the source changes (M2-T1)."""
		frappe.cache.delete_value(runner.COUNT_CACHE.format(key))


class TestAccess(ApiTestCase):
	def test_guests_and_website_users_are_refused_by_every_endpoint(self):
		self.assertEqual(frappe.db.get_value("User", self.website_user, "user_type"), "Website User")

		for user in ("Guest", self.website_user):
			frappe.set_user(user)
			for endpoint, arguments in ENDPOINTS.items():
				with self.subTest(user=user, endpoint=endpoint):
					with self.assertRaises(frappe.PermissionError):
						frappe.call(f"{API}.{endpoint}", **arguments)

		self.assertFalse(frappe.db.exists(PREFERENCE, {"user": ("in", ("Guest", self.website_user))}))

	def test_changes_are_accepted_over_post_only(self):
		request = getattr(frappe.local, "request", None)
		try:
			for endpoint in (api.mark_seen, api.set_preferences, api.note_auto_opened):
				with self.subTest(endpoint=endpoint.__name__):
					frappe.local.request = frappe._dict(method="POST")
					is_valid_http_method(endpoint)
					frappe.local.request = frappe._dict(method="GET")
					with self.assertRaises(frappe.PermissionError):
						is_valid_http_method(endpoint)
		finally:
			frappe.local.request = request


class TestGetSummary(ApiTestCase):
	def test_each_visible_source_is_counted_for_the_session_user(self):
		add_todo(self.user, "High and overdue", priority="High", date=add_days(today(), -1))
		newest = add_todo(self.user, "Plain")
		add_todo(self.other_user, "Someone else's")

		summary = api.get_summary()

		self.assertEqual([source["key"] for source in summary["sources"]], [TODOS, FEED, NUMBERS])
		self.assertEqual(
			summary["sources"][0],
			{
				"key": TODOS,
				"label": "Open tasks",
				"kind": "action",
				"icon": None,
				"list_route": "/app/todo",
				"state": "ok",
				"count": 2,
				"capped": False,
				"urgent": 1,
				"immediate": 0,
				"overdue": 1,
				"new_since": 2,
				"latest": frappe.db.get_value("ToDo", newest, "creation").isoformat(timespec="seconds"),
			},
		)
		self.assertEqual(summary["sources"][1]["kind"], "info")
		self.assertIsInstance(datetime.fromisoformat(summary["generated_at"]), datetime)

	def test_totals_add_up_action_counts_attention_items_and_new_info(self):
		add_todo(self.user, "High and overdue", priority="High", date=add_days(today(), -1))
		add_todo(self.user, "Plain")

		# The overdue urgent task counts twice in attention, as §5 accepts; the info source only adds to info_new.
		self.assertEqual(api.get_summary()["totals"], {"action": 2, "attention": 2, "info_new": 3})

	def test_a_failing_source_is_an_error_entry_and_adds_nothing(self):
		frappe.set_user("Administrator")
		add_python_source(BROKEN, "Action", "count_that_raises", "items_that_raise", sort_order=5)
		registry.clear_visibility_cache()
		frappe.set_user(self.user)
		add_todo(self.user, "Plain")

		with self.assertLogs(frappe.logger("attention_center"), "ERROR"):
			summary = api.get_summary()

		broken = next(source for source in summary["sources"] if source["key"] == BROKEN)
		self.assertEqual((broken["state"], broken["count"]), ("error", 0))
		self.assertEqual(summary["totals"]["action"], 1)

	def test_the_summary_is_empty_while_the_attention_center_is_disabled(self):
		add_todo(self.user, "Plain")
		frappe.set_user("Administrator")
		update_settings(enabled=0)
		frappe.set_user(self.user)

		summary = api.get_summary()

		self.assertEqual(
			{"sources": summary["sources"], "totals": summary["totals"]},
			{"sources": [], "totals": {"action": 0, "attention": 0, "info_new": 0}},
		)

	def test_another_users_summary_cannot_be_requested(self):
		add_todo(self.user, "Mine")
		add_todo(self.user, "Also mine")
		add_todo(self.other_user, "Theirs")
		frappe.set_user(self.other_user)

		summary = frappe.call(f"{API}.get_summary", user=self.user)

		self.assertEqual(summary["sources"][0]["count"], 1)


class TestGetItems(ApiTestCase):
	def test_items_come_most_pressing_first_one_page_at_a_time(self):
		add_todo(self.user, "Plain")
		add_todo(self.user, "Overdue", date=add_days(today(), -1))
		add_todo(self.user, "High", priority="High")

		first = api.get_items(TODOS, page_length=2)
		second = api.get_items(TODOS, start=2, page_length=2)

		self.assertEqual(
			([item["title"] for item in first["items"]], first["has_more"]), (["Overdue", "High"], True)
		)
		self.assertEqual(
			([item["title"] for item in second["items"]], second["has_more"]), (["Plain"], False)
		)
		self.assertEqual(first["state"], "ok")

	def test_the_page_length_defaults_to_the_settings_and_is_clamped(self):
		self.assertEqual(len(api.get_items(NUMBERS)["items"]), 10)
		frappe.set_user("Administrator")
		update_settings(page_size=7)
		frappe.set_user(self.user)

		self.assertEqual(len(api.get_items(NUMBERS)["items"]), 7)
		self.assertEqual(len(api.get_items(NUMBERS, page_length=0)["items"]), 1)
		self.assertEqual(len(api.get_items(NUMBERS, page_length=500)["items"]), 50)
		self.assertTrue(api.get_items(NUMBERS, page_length=500)["has_more"])

	def test_arguments_of_the_wrong_type_or_out_of_bounds_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			api.get_items(TODOS, start=-1)
		for arguments in ({"start": "first"}, {"page_length": "all"}, {"source": ["a", "b"]}):
			with self.subTest(arguments=arguments), self.assertRaises(FrappeTypeError):
				api.get_items(**{"source": TODOS, **arguments})

	def test_a_source_the_user_does_not_see_is_refused_like_a_missing_one(self):
		frappe.set_user("Administrator")
		frappe.db.set_value(SOURCE, NUMBERS, "enabled", 0)
		registry.clear_visibility_cache()
		frappe.set_user(self.user)

		messages = set()
		for key in (RESTRICTED, NUMBERS, "test_app.missing"):
			with self.subTest(key=key), self.assertRaises(frappe.PermissionError) as refused:
				api.get_items(key)
			messages.add(str(refused.exception))
		self.assertEqual(len(messages), 1, "the error does not tell a hidden source from a missing one")

	def test_no_source_is_open_while_the_attention_center_is_disabled(self):
		frappe.set_user("Administrator")
		update_settings(enabled=0)
		frappe.set_user(self.user)

		with self.assertRaises(frappe.PermissionError):
			api.get_items(TODOS)

	def test_a_failing_source_returns_an_error_state(self):
		frappe.set_user("Administrator")
		add_python_source(BROKEN, "Action", "no_count", "items_that_raise", sort_order=5)
		registry.clear_visibility_cache()
		frappe.set_user(self.user)

		with self.assertLogs(frappe.logger("attention_center"), "ERROR"):
			self.assertEqual(api.get_items(BROKEN), {"state": "error", "items": [], "has_more": False})

	def test_another_users_items_cannot_be_requested(self):
		add_todo(self.user, "Mine")
		add_todo(self.other_user, "Theirs")
		frappe.set_user(self.other_user)

		result = frappe.call(f"{API}.get_items", source=TODOS, user=self.user)

		self.assertEqual([item["title"] for item in result["items"]], ["Theirs"])


class TestMarkSeen(ApiTestCase):
	def test_viewing_a_source_resets_its_new_since(self):
		add_todo(self.user, "Seen soon")
		self.assertEqual(self.source_entry(TODOS)["new_since"], 1)

		frappe.call(f"{API}.mark_seen", source=TODOS)

		self.assertEqual(self.source_entry(TODOS)["new_since"], 0)
		self.assertEqual(self.source_entry(TODOS)["count"], 1)
		self.assertEqual(self.source_entry(FEED)["new_since"], 3, "other sources keep their watermark")
		add_todo(self.user, "Arrived later")
		self.forget_counts(TODOS)
		self.assertEqual(self.source_entry(TODOS)["new_since"], 1)

	def test_without_a_source_every_visible_source_is_marked(self):
		before = now_datetime()
		api.mark_seen()

		watermarks = json.loads(stored_preference(self.user).watermarks)
		self.assertEqual(set(watermarks), {TODOS, FEED, NUMBERS})
		self.assertTrue(all(datetime.fromisoformat(seen) >= before for seen in watermarks.values()))
		self.assertEqual(self.source_entry(FEED)["new_since"], 1)

	def test_a_hidden_source_cannot_be_marked(self):
		with self.assertRaises(frappe.PermissionError):
			api.mark_seen(RESTRICTED)

		self.assertIsNone(stored_preference(self.user))

	def test_marking_changes_only_the_users_own_watermarks(self):
		add_todo(self.other_user, "Theirs")
		frappe.call(f"{API}.mark_seen", source=TODOS, user=self.other_user)

		self.assertIsNone(stored_preference(self.other_user))
		frappe.set_user(self.other_user)
		self.assertEqual(self.source_entry(TODOS)["new_since"], 1)


class TestPreferences(ApiTestCase):
	def test_unset_preferences_follow_the_settings_defaults(self):
		self.assertEqual(api.get_preferences(), DEFAULT_PREFERENCES)

		frappe.set_user("Administrator")
		update_settings(
			default_display_mode="Drawer",
			default_auto_open_on_login=0,
			default_sound_scope="Everything",
			default_tone="knock",
			default_volume=30,
		)
		frappe.set_user(self.user)

		self.assertEqual(
			api.get_preferences(),
			{
				**DEFAULT_PREFERENCES,
				"display_mode": "Drawer",
				"auto_open_on_login": False,
				"sound_scope": "Everything",
				"tone": "knock",
				"volume": 30,
			},
		)

	def test_the_users_own_values_override_the_defaults_until_reset(self):
		dnd_until = (now_datetime() + timedelta(hours=1)).replace(microsecond=0)
		own = {
			"display_mode": "Panel",
			"auto_open_on_login": "No",
			"sound_scope": "Urgent Only",
			"tone": "drop",
			"volume": 0,
			"dnd_until": dnd_until.isoformat(),
			"launcher_collapsed": True,
		}
		effective = {
			"display_mode": "Panel",
			"auto_open_on_login": False,
			"sound_scope": "Urgent Only",
			"tone": "drop",
			"volume": 0,
			"dnd_until": dnd_until.isoformat(),
			"launcher_collapsed": True,
		}

		self.assertEqual(frappe.call(f"{API}.set_preferences", prefs=own), effective)
		self.assertEqual(api.get_preferences(), effective)
		self.assertEqual(api.set_preferences({"volume": 35}), {**effective, "volume": 35}, "others are kept")

		reset = {
			"display_mode": "Default",
			"auto_open_on_login": "Default",
			"sound_scope": "",
			"tone": "",
			"volume": "",
			"dnd_until": None,
			"launcher_collapsed": 0,
		}
		self.assertEqual(api.set_preferences(reset), DEFAULT_PREFERENCES)

	def test_a_first_write_that_loses_the_race_to_create_the_row_still_applies(self):
		api.set_preferences({"volume": 20})
		exists = frappe.db.exists
		answers = iter([False])

		def exists_as_seen_before_the_other_request_committed(doctype, *args, **kwargs):
			if doctype == PREFERENCE:
				return next(answers, True)
			return exists(doctype, *args, **kwargs)

		with patch.object(frappe.db, "exists", side_effect=exists_as_seen_before_the_other_request_committed):
			api.set_preferences({"display_mode": "Panel"})

		self.assertEqual(
			(stored_preference(self.user).volume, stored_preference(self.user).display_mode), ("20", "Panel")
		)

	def test_preferences_sent_as_json_text_are_read(self):
		self.assertEqual(api.set_preferences(json.dumps({"volume": "45"}))["volume"], 45)

	def test_a_do_not_disturb_time_is_read_in_its_time_zone_and_ends(self):
		in_two_hours = (datetime.now(timezone(timedelta(hours=-3))) + timedelta(hours=2)).replace(
			microsecond=0
		)
		expected = in_two_hours.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)

		self.assertEqual(
			api.set_preferences({"dnd_until": in_two_hours.isoformat()})["dnd_until"], expected.isoformat()
		)

		an_hour_ago = (now_datetime() - timedelta(hours=1)).isoformat(timespec="seconds")
		self.assertIsNone(api.set_preferences({"dnd_until": an_hour_ago})["dnd_until"], "it has ended")

	def test_invalid_values_are_rejected(self):
		invalid = {
			"sound_scope": ["Loud", 1, None],
			"tone": ["urgent", "reminder", "siren", "Chime"],
			"volume": [101, -1, "loud", 50.5, True],
			"dnd_until": ["tomorrow", "2026-11-12", 1794314119, "12:00"],
			"auto_open_on_login": [True, "Maybe", ""],
			"display_mode": ["Popup", "dialog", None],
			"launcher_collapsed": [2, "yes", 0.5, None],
		}
		for fieldname, values in invalid.items():
			for value in values:
				with self.subTest(fieldname=fieldname, value=value):
					with self.assertRaises(frappe.ValidationError):
						api.set_preferences({fieldname: value})

		self.assertEqual(api.get_preferences(), DEFAULT_PREFERENCES)

	def test_unknown_names_are_rejected_so_stored_state_cannot_be_written(self):
		for prefs in (
			{"watermarks": {TODOS: "2030-01-01T00:00:00"}},
			{"last_auto_open_sid": "forged"},
			{"user": self.other_user, "volume": 10},
			{"name": self.other_user, "volume": 10},
			{"colour": "green"},
		):
			with self.subTest(prefs=prefs), self.assertRaises(frappe.ValidationError):
				api.set_preferences(prefs)

		self.assertIsNone(stored_preference(self.user))
		self.assertIsNone(stored_preference(self.other_user))

	def test_preferences_must_be_an_object(self):
		for prefs in ("[1, 2]", "not json", '"volume"'):
			with self.subTest(prefs=prefs), self.assertRaises(frappe.ValidationError):
				api.set_preferences(prefs)

	def test_users_read_and_write_only_their_own_preferences(self):
		api.set_preferences({"display_mode": "Drawer", "volume": 15})

		frappe.set_user(self.other_user)
		self.assertEqual(frappe.call(f"{API}.get_preferences", user=self.user), DEFAULT_PREFERENCES)
		frappe.call(f"{API}.set_preferences", prefs={"volume": 90}, user=self.user)

		self.assertEqual(
			(stored_preference(self.user).volume, stored_preference(self.other_user).volume), ("15", "90")
		)


class TestAutoOpen(ApiTestCase):
	def should_auto_open(self) -> bool:
		bootinfo = frappe._dict()
		boot.extend_bootinfo(bootinfo)
		return bootinfo.attention_center["should_auto_open"]

	def test_the_window_opens_by_itself_once_per_login_session(self):
		frappe.session.sid = "first-session-id"
		self.assertTrue(self.should_auto_open())

		frappe.call(f"{API}.note_auto_opened")

		self.assertFalse(self.should_auto_open())
		frappe.session.sid = "second-session-id"
		self.assertTrue(self.should_auto_open(), "a new login session opens it again")

	def test_only_a_hash_of_the_session_id_is_stored(self):
		frappe.session.sid = "first-session-id"
		api.note_auto_opened()

		self.assertEqual(
			stored_preference(self.user).last_auto_open_sid,
			hashlib.sha256(b"first-session-id").hexdigest(),
		)

	def test_noting_concerns_only_the_users_own_session(self):
		frappe.session.sid = "first-session-id"
		frappe.call(f"{API}.note_auto_opened", user=self.other_user)

		self.assertIsNone(stored_preference(self.other_user))


class TestTestSource(ApiTestCase):
	def test_a_manager_gets_counts_first_items_and_duration_as_themselves(self):
		add_todo(self.manager, "Manager's task")
		add_todo(self.user, "Someone else's task")
		frappe.set_user(self.manager)

		result = api.test_source(TODOS)
		numbers = api.test_source(NUMBERS)

		self.assertEqual((result["count"]["state"], result["count"]["count"]), ("ok", 1))
		self.assertEqual([item["title"] for item in result["items"]["items"]], ["Manager's task"])
		self.assertIsInstance(result["duration_ms"], int)
		self.assertEqual(len(numbers["items"]["items"]), 5)

	def test_a_disabled_source_can_be_tested_and_its_count_is_fresh(self):
		frappe.set_user(self.manager)
		add_todo(self.manager, "First")
		self.assertEqual(api.test_source(TODOS)["count"]["count"], 1)
		frappe.set_user("Administrator")
		frappe.db.set_value(SOURCE, TODOS, "enabled", 0)
		frappe.set_user(self.manager)
		add_todo(self.manager, "Second")

		self.assertEqual(api.test_source(TODOS)["count"]["count"], 2, "not the count cached a moment ago")

	def test_a_system_manager_may_test_a_source_too(self):
		frappe.set_user("Administrator")
		system_manager = make_user("api.system@example.com", ["System Manager"])
		add_todo(system_manager, "System Manager's task")
		frappe.set_user(system_manager)

		self.assertEqual(api.test_source(TODOS)["count"]["count"], 1)

	def test_a_manager_who_cannot_read_the_doctype_gets_an_error_and_no_rows(self):
		frappe.set_user("Administrator")
		frappe.get_doc(
			{
				"doctype": SOURCE,
				"key": ROLE_PROFILES,
				"label": "Role profiles",
				"kind": "Info",
				"reference_doctype": "Role Profile",
				"title_field": "role_profile",
				"date_field": "creation",
				"filters_json": json.dumps([["role_profile", "=", "_Test Attention Profile"]]),
			}
		).insert()
		frappe.get_doc({"doctype": "Role Profile", "role_profile": "_Test Attention Profile"}).insert()
		self.assertEqual(api.test_source(ROLE_PROFILES)["count"]["count"], 1)
		self.assertFalse(frappe.has_permission("Role Profile", "read", user=self.manager))
		frappe.set_user(self.manager)

		with self.assertLogs(frappe.logger("attention_center"), "ERROR"):
			result = api.test_source(ROLE_PROFILES)

		self.assertEqual((result["count"]["state"], result["count"]["count"]), ("error", 0))
		self.assertEqual(result["items"], {"state": "error", "items": []})

	def test_users_without_a_manager_role_are_refused(self):
		with self.assertRaises(frappe.PermissionError):
			api.test_source(TODOS)

	def test_reading_the_sources_is_not_enough_without_a_manager_role(self):
		frappe.set_user("Administrator")
		reader_role = make_desk_role("_Test Attention Source Reader")
		add_permission(SOURCE, reader_role)
		self.addCleanup(frappe.clear_cache, doctype=SOURCE)
		frappe.set_user(make_user("api.reader@example.com", [reader_role]))
		self.assertTrue(frappe.has_permission(SOURCE, "read"))

		with self.assertRaises(frappe.PermissionError):
			api.test_source(TODOS)

	def test_a_missing_source_is_reported(self):
		frappe.set_user(self.manager)

		with self.assertRaises(frappe.DoesNotExistError):
			api.test_source("test_app.missing")
