"""Endpoints of the desk client (§5).

Every endpoint acts for the session user, who must be a desk user, and none takes a user id [FR-PERM-01].
"""

import json
from time import perf_counter

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import is_system_user
from frappe.utils import cint, now_datetime

from attention_center.engine import preferences, registry, runner
from attention_center.permissions import is_manager
from attention_center.sources import announcements

SETTINGS = "Attention Center Settings"
SOURCE = "Attention Source"
MAX_PAGE_LENGTH = 50
TEST_SOURCE_ITEMS = 5


@frappe.whitelist()
def get_summary() -> dict:
	"""Counts of every source the user sees, and the totals the launcher shows [FR-API-01]."""
	user = _desk_user()
	watermarks = preferences.get_watermarks(preferences.get_stored())
	sources = [
		_summary_entry(source, runner.run_count(source, user, watermarks.get(source.key)))
		for source in _visible_sources(user)
	]
	actions = [source for source in sources if source["kind"] == "action"]
	return {
		"generated_at": now_datetime().isoformat(timespec="seconds"),
		"sources": sources,
		"totals": {
			"action": sum(source["count"] for source in actions),
			# An item both urgent and overdue counts twice (§5).
			"attention": sum(
				source["urgent"] + source["immediate"] + source["overdue"] for source in actions
			),
			"info_new": sum(source["new_since"] for source in sources if source["kind"] == "info"),
		},
	}


@frappe.whitelist()
def get_items(source: str, start: int = 0, page_length: int | None = None) -> dict:
	"""One page of a visible source's items, most pressing first [FR-API-02].

	`page_length` defaults to the settings' page size and is clamped to 1..MAX_PAGE_LENGTH.
	"""
	user = _desk_user()
	if start < 0:
		frappe.throw(_("Start must be 0 or more."))
	if page_length is None:
		page_length = cint(_settings().page_size)
	page_length = min(max(page_length, 1), MAX_PAGE_LENGTH)

	# One item more than the page tells whether another page follows.
	result = runner.run_items(_visible_source(user, source), user, start, page_length + 1)
	return {
		"state": result["state"],
		"items": result["items"][:page_length],
		"has_more": len(result["items"]) > page_length,
	}


@frappe.whitelist(methods=["POST"])
def mark_seen(source: str | None = None) -> None:
	"""Mark one visible source, or every visible source, as seen now [FR-API-03]."""
	user = _desk_user()
	if source is None:
		keys = [visible.key for visible in _visible_sources(user)]
	else:
		keys = [_visible_source(user, source).key]
	preferences.mark_seen(keys)


@frappe.whitelist()
def get_preferences() -> dict:
	"""The user's effective preferences: their own values over the settings' defaults [FR-API-04]."""
	_desk_user()
	return preferences.get_effective(preferences.get_stored())


@frappe.whitelist(methods=["POST"])
def set_preferences(prefs: dict | str) -> dict:
	"""Change some of the user's own preferences; returns the effective preferences [FR-API-04]."""
	_desk_user()
	if isinstance(prefs, str):
		# frappe.call sends an object argument as JSON text.
		try:
			prefs = json.loads(prefs)
		except ValueError:
			prefs = None
	return preferences.set_preferences(prefs)


@frappe.whitelist(methods=["POST"])
def note_auto_opened() -> None:
	"""Record that the window opened by itself in this login session [FR-ALERT-05]."""
	_desk_user()
	preferences.note_auto_opened()


@frappe.whitelist()
def test_source(source: str) -> dict:
	"""Run any source, enabled or not, for the calling manager: its counts, first items and duration.

	The source runs with the caller's own permissions, so it shows nothing they could not open anyway.
	"""
	user = _desk_user()
	if not is_manager(user):
		frappe.throw(_("Only an Attention Manager can test a source."), frappe.PermissionError)
	rows = frappe.get_list(SOURCE, filters={"name": source}, fields=list(registry.SOURCE_FIELDS))
	if not rows:
		frappe.throw(_("This source does not exist."), frappe.DoesNotExistError)

	# The manager may have just changed the definition: a cached count would describe the old one.
	frappe.cache.hdel(runner.COUNT_CACHE.format(source), user)
	started = perf_counter()
	count = runner.run_count(rows[0], user)
	items = runner.run_items(rows[0], user, 0, TEST_SOURCE_ITEMS)
	return {"count": count, "items": items, "duration_ms": round((perf_counter() - started) * 1000)}


@frappe.whitelist(methods=["POST"])
def acknowledge_announcement(announcement: str) -> dict:
	"""Acknowledge an announcement the user receives; acknowledging again keeps the first time [FR-ANN-03]."""
	_desk_user()
	acknowledged_at = announcements.acknowledge(announcement)
	return {"announcement": announcement, "acknowledged_at": acknowledged_at.isoformat(timespec="seconds")}


@frappe.whitelist()
def get_announcement_receipts(announcement: str) -> dict:
	"""For managers: who acknowledged an announcement and when, and who in its audience has not [FR-ANN-04]."""
	user = _desk_user()
	if not is_manager(user):
		frappe.throw(
			_("Only an Attention Manager can see who acknowledged an announcement."), frappe.PermissionError
		)
	return announcements.receipts(announcement)


def _desk_user() -> str:
	"""The session user, who must be logged in with desk access: a source without targeting is meant for
	every desk user, not for website users or guests."""
	if not is_system_user():
		frappe.throw(_("The Attention Center is available to desk users only."), frappe.PermissionError)
	return frappe.session.user


def _visible_sources(user: str) -> list[frappe._dict]:
	"""No source is visible while the Attention Center is disabled in the settings."""
	return registry.get_visible_sources(user) if _settings().enabled else []


def _visible_source(user: str, key: str) -> frappe._dict:
	"""The visible source with this key. A hidden source and a missing one get the same error, so that the
	error does not tell which sources exist [FR-API-02 AC1]."""
	for source in _visible_sources(user):
		if source.key == key:
			return source
	frappe.throw(_("This source is not available to you."), frappe.PermissionError)


def _summary_entry(source: frappe._dict, counts: dict) -> dict:
	return {
		"key": source.key,
		# Labels Frappe also translates carry the DocType as context in ar.csv.
		"label": _(source.label, context=SOURCE),
		"kind": source.kind.lower(),
		"icon": source.icon,
		"list_route": source.list_route,
		**counts,
	}


def _settings() -> Document:
	return frappe.get_cached_doc(SETTINGS)
