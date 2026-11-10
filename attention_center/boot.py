"""The Attention Center's part of the desk boot (§5)."""

import frappe
from frappe.permissions import is_system_user
from frappe.utils import cint, flt

from attention_center import __version__
from attention_center.engine import preferences

SETTINGS = "Attention Center Settings"


def extend_bootinfo(bootinfo: frappe._dict) -> None:
	"""Add `attention_center`: whether the client runs, its settings, the effective preferences and the tones.

	Reads the cached settings and one preference row and runs no source, so the desk never waits for one;
	counts come later from get_summary [NFR-PERF-02]. A failure turns the client off for this page load
	instead of breaking the desk [NFR-REL-01].
	"""
	try:
		boot = _boot()
	except Exception as error:
		frappe.logger("attention_center").error(
			f"boot info failed for {frappe.session.user}: {type(error).__name__}"
		)
		boot = {"enabled": False}
	bootinfo["attention_center"] = boot


def _boot() -> dict:
	settings = frappe.get_cached_doc(SETTINGS)
	if not (settings.enabled and is_system_user()):
		return {"enabled": False}

	stored = preferences.get_stored()
	return {
		"enabled": True,
		"version": __version__,
		"settings": {
			"hide_standard_bell": bool(settings.hide_standard_bell),
			"urgent_tone": settings.urgent_tone,
			"immediate_tone": settings.immediate_tone,
			"reminder_tone": settings.reminder_tone,
			"reminder_interval_hours": flt(settings.reminder_interval_hours),
			"coalesce_seconds": cint(settings.coalesce_seconds),
			"heartbeat_seconds": cint(settings.heartbeat_seconds),
			"page_size": cint(settings.page_size),
		},
		"preferences": preferences.get_effective(stored),
		"should_auto_open": preferences.should_auto_open(stored),
		"tones": preferences.get_tones(),
	}
