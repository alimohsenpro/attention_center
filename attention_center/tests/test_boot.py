import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from attention_center import __version__, api, boot
from attention_center.engine import preferences, registry, runner
from attention_center.tests.utils import make_desk_role, make_user

SOURCE = "Attention Source"
SETTINGS = "Attention Center Settings"
RECORDED = "test_app.recorded"
# Document content that must never reach a log.
SECRET_TITLE = "Quarterly salary review"
SOURCE_CALLS: list[str] = []


def recorded_count(user: str) -> int:
	SOURCE_CALLS.append(user)
	return 1


def recorded_items(user: str, start: int, page_length: int) -> list[dict]:
	SOURCE_CALLS.append(user)
	return []


def bootinfo_for(user: str) -> dict:
	frappe.set_user(user)
	bootinfo = frappe._dict()
	boot.extend_bootinfo(bootinfo)
	return bootinfo.attention_center


class TestBootInfo(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.user = make_user("boot.user@example.com", [make_desk_role("_Test Attention Boot Role")])
		settings = frappe.get_single(SETTINGS)
		settings.update(
			{
				"enabled": 1,
				"hide_standard_bell": 1,
				"default_display_mode": "Panel",
				"default_auto_open_on_login": 1,
				"default_sound_scope": "Everything",
				"default_tone": "knock",
				"default_volume": 40,
				"urgent_tone": "urgent",
				"immediate_tone": "immediate",
				"reminder_tone": "reminder",
				"reminder_interval_hours": 1.5,
				"coalesce_seconds": 15,
				"heartbeat_seconds": 120,
				"page_size": 20,
			}
		)
		settings.save()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		registry.clear_visibility_cache()
		frappe.cache.delete_value(runner.COUNT_CACHE.format(RECORDED))
		SOURCE_CALLS.clear()

	def test_the_hook_is_registered(self):
		self.assertIn("attention_center.boot.extend_bootinfo", frappe.get_hooks("extend_bootinfo"))

	def test_a_desk_user_gets_settings_effective_preferences_and_tones(self):
		frappe.set_user(self.user)
		api.set_preferences({"volume": 25, "display_mode": "Drawer"})

		info = bootinfo_for(self.user)

		self.assertEqual(
			{key: value for key, value in info.items() if key != "tones"},
			{
				"enabled": True,
				"version": __version__,
				"settings": {
					"hide_standard_bell": True,
					"urgent_tone": "urgent",
					"immediate_tone": "immediate",
					"reminder_tone": "reminder",
					"reminder_interval_hours": 1.5,
					"coalesce_seconds": 15,
					"heartbeat_seconds": 120,
					"page_size": 20,
				},
				"preferences": {
					"display_mode": "Drawer",
					"auto_open_on_login": True,
					"sound_scope": "Everything",
					"tone": "knock",
					"volume": 25,
					"dnd_until": None,
					"launcher_collapsed": False,
				},
				"should_auto_open": True,
			},
		)

	def test_the_tones_are_those_of_tones_json_with_their_urls(self):
		with open(frappe.get_app_path("attention_center", "public", "sounds", "tones.json")) as file:
			declared = json.load(file)

		tones = bootinfo_for(self.user)["tones"]

		self.assertEqual(
			[(tone["id"], tone["role"], tone["label"]) for tone in tones],
			[(tone["id"], tone["role"], tone["label"]) for tone in declared],
		)
		self.assertEqual(tones[0]["url"], f"/assets/attention_center/sounds/{declared[0]['file']}")
		self.assertEqual({tone["role"] for tone in tones}, {"standard", "urgent", "immediate", "reminder"})

	def test_the_client_stays_off_when_disabled_and_for_guests_and_website_users(self):
		website_user = make_user("boot.website@example.com", [])
		self.assertEqual(bootinfo_for("Guest"), {"enabled": False})
		self.assertEqual(bootinfo_for(website_user), {"enabled": False})

		frappe.set_user("Administrator")
		frappe.db.set_single_value(SETTINGS, "enabled", 0)
		frappe.clear_document_cache(SETTINGS, SETTINGS)

		self.assertEqual(bootinfo_for(self.user), {"enabled": False})

	def test_no_source_runs_during_boot(self):
		doc = frappe.get_doc(
			{
				"doctype": SOURCE,
				"key": RECORDED,
				"label": "Recorded",
				"kind": "Action",
				"source_type": "Python",
				"is_system": 1,
				"app": "attention_center",
				"get_count": f"{__name__}.recorded_count",
				"get_items": f"{__name__}.recorded_items",
			}
		)
		doc.flags.from_hooks = True
		doc.insert()

		bootinfo_for(self.user)
		self.assertEqual(SOURCE_CALLS, [], "the boot ran a source")

		api.get_summary()
		self.assertEqual(SOURCE_CALLS, [self.user], "the summary does run it")

	def test_a_failure_turns_the_client_off_without_breaking_the_boot(self):
		frappe.set_user(self.user)
		bootinfo = frappe._dict(sitename="kept")

		with (
			patch.object(preferences, "get_effective", side_effect=frappe.ValidationError(SECRET_TITLE)),
			self.assertLogs(frappe.logger("attention_center"), "ERROR") as logs,
		):
			boot.extend_bootinfo(bootinfo)

		self.assertEqual(bootinfo, {"sitename": "kept", "attention_center": {"enabled": False}})
		self.assertEqual(len(logs.output), 1)
		self.assertIn(f"boot info failed for {self.user}: ValidationError", logs.output[0])
		self.assertNotIn(SECRET_TITLE, logs.output[0])
