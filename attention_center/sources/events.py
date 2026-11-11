"""Built-in source of today's calendar events: what the user's Frappe calendar shows for today (§4.5) [FR-EXT-01]."""

from datetime import date, datetime, time

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, add_years, cint, get_datetime, getdate

from attention_center.engine.contract import COUNT_CAP

EVENT = "Event"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
FIELDS = (
	"name",
	"subject",
	"starts_on",
	"ends_on",
	"all_day",
	"event_category",
	"owner",
	"modified",
	"repeat_this_event",
	"repeat_on",
	"repeat_till",
	*WEEKDAYS,
)


def get_count(user: str, since: datetime | None = None) -> dict:
	"""An event joins today's list when the day starts, or when it is added or changed during the day: from then on
	it is new to a user who last looked before."""
	day = getdate()
	arrivals = [max(event.modified, _midnight(day)) for event in _today(user, day)]
	return {
		"count": len(arrivals),
		"latest": max(arrivals, default=None),
		"new_since": len(arrivals) if since is None else sum(arrival > since for arrival in arrivals),
	}


def get_items(user: str, start: int, page_length: int) -> list[dict]:
	"""Today's events in the order of the day: all-day ones first, then by start time."""
	day = getdate()
	events = sorted(_today(user, day), key=lambda event: (not event.all_day, _start(event, day)))
	return [_item(event, day) for event in events[start : start + page_length]]


def get_recipients(doc: Document) -> list[str]:
	"""Whose list of today's events the change of `doc` moves: nobody when the event neither was nor is on today;
	every desk user when it was or is public (above the audience cap the engine nudges the whole site); else its
	owner and participants. Runs in the actor's request, so it reads no session user."""
	day = getdate()
	versions = [version for version in (doc, doc.get_doc_before_save()) if version]
	if not any(occurs_on(version, day) for version in versions):
		return []
	if any(version.event_type == "Public" for version in versions):
		# get_all: lists whom to nudge with a content-free signal; nobody sees the list.
		return frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, pluck="name")
	return [
		user
		for version in versions
		for user in (version.owner, *(row.email for row in version.event_participants))
		if user
	]


def occurs_on(event: frappe._dict | Document, day: date) -> bool:
	"""Whether the event takes place on `day`, as Frappe's calendar repeats it: a one-off event on every day from its
	start to its end, a repeating one on the days an occurrence starts, until `repeat_till`."""
	starts_on = get_datetime(event.starts_on)
	start = starts_on.date()
	if not cint(event.repeat_this_event):
		end = get_datetime(event.ends_on).date() if event.ends_on else start
		return start <= day <= end
	if start > day or (event.repeat_till and getdate(event.repeat_till) < day):
		return False
	if event.repeat_on == "Daily":
		return True
	if event.repeat_on == "Weekly":
		return bool(cint(event.get(WEEKDAYS[day.weekday()])))
	if event.repeat_on == "Monthly":
		months = (day.year - start.year) * 12 + day.month - start.month
		return getdate(add_months(start, months)) == day
	if event.repeat_on == "Yearly":
		return getdate(add_years(start, day.year - start.year)) == day
	return False


def _today(user: str, day: date) -> list[frappe._dict]:
	"""The open events on `day` that the user may read: frappe.get_list applies Event's own rules (their events, public
	ones and those they take part in). One-off events overlapping the day are read before repeating series, newest
	first, and at most COUNT_CAP + 1 of them: a site with more open repeating series checks only the newest."""
	midnight = _midnight(day)
	candidates = frappe.get_list(
		EVENT,
		filters=[["status", "=", "Open"], ["starts_on", "<", add_days(midnight, 1)]],
		or_filters=[
			["starts_on", ">=", midnight],
			["ends_on", ">=", midnight],
			["repeat_this_event", "=", 1],
		],
		fields=list(FIELDS),
		order_by="repeat_this_event asc, starts_on desc, name desc",
		limit_page_length=COUNT_CAP + 1,
		user=user,
	)
	return [event for event in candidates if occurs_on(event, day)]


def _start(event: frappe._dict, day: date) -> datetime:
	"""When the event starts: a repeating event's occurrence starts on `day`."""
	if event.repeat_this_event:
		return datetime.combine(day, event.starts_on.time())
	return event.starts_on


def _midnight(day: date) -> datetime:
	return datetime.combine(day, time.min)


def _item(event: frappe._dict, day: date) -> dict:
	return {
		"id": event.name,
		"title": event.subject,
		"reference_doctype": EVENT,
		"reference_name": event.name,
		# Frappe translates its own categories (Event, Meeting, Call, …).
		"type_label": _(event.event_category) if event.event_category else None,
		"from_user": event.owner,
		"date": None if event.all_day else _start(event, day),
		"status_label": _("All day", context="Attention Center") if event.all_day else None,
	}
