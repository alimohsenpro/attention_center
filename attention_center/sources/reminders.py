"""Built-in source of the user's due reminders, and "Remind me later" on an item: both are Frappe's Reminder, which
also sends the user a notification when it falls due (§4.5, §5) [FR-EXT-01, FR-SNZ-01]."""

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from attention_center.engine.contract import COUNT_CAP, TITLE_MAX_LENGTH, parse_when, plain_text

REMINDER = "Reminder"
# A reminder has no "done" state: it stays listed for a day after it falls due, so that one falling due after the
# user left is still there the next morning.
LISTED_FOR = timedelta(hours=24)


def get_count(user: str, since: datetime | None = None) -> dict:
	"""A reminder is new to a user who last looked before it fell due."""
	dates = [row.remind_at for row in _due(user)]
	return {
		"count": len(dates),
		"latest": max(dates, default=None),
		"new_since": len(dates) if since is None else sum(date > since for date in dates),
	}


def get_items(user: str, start: int, page_length: int) -> list[dict]:
	"""The reminders that fell due, the latest first; each opens the document it is about."""
	return [_item(row) for row in _due(user)[start : start + page_length]]


def get_recipients(doc: Document) -> list[str]:
	"""A reminder is its user's own."""
	return [doc.user]


def remind(remind_at: object, title: object, reference_doctype: object, reference_name: object) -> Document:
	"""Set a reminder for the session user at `remind_at` (naive, in the system time zone, or with an offset), about
	the document named by `reference_doctype` and `reference_name` when given, which they must be able to read. The
	title of the item becomes its description, which Frappe's notification shows when it falls due [FR-SNZ-01]."""
	when = parse_when(remind_at)
	if not isinstance(when, datetime) or when <= now_datetime():
		frappe.throw(_("Choose a date and time later than now."))
	description = plain_text(title)
	if not description:
		frappe.throw(_("Say what the reminder is about."))
	if reference_doctype or reference_name:
		_check_readable(reference_doctype, reference_name)

	# Inserted as the session user, with the permissions Frappe gives desk users on their own reminders; the
	# controller makes the reminder theirs.
	return frappe.get_doc(
		{
			"doctype": REMINDER,
			"remind_at": when,
			"description": description[:TITLE_MAX_LENGTH],
			"reminder_doctype": reference_doctype or None,
			"reminder_docname": reference_name or None,
		}
	).insert()


def _check_readable(doctype: object, name: object) -> None:
	"""A reminder may name only a document the user can read. A missing document gets the same answer, so that the
	error tells nothing about which documents exist."""
	readable = False
	if isinstance(doctype, str) and isinstance(name, str) and doctype and name:
		queued_messages = len(frappe.local.message_log)
		try:
			readable = frappe.has_permission(doctype, "read", name)
		except frappe.DoesNotExistError:
			# Frappe queues a "not found" message, which would name the document.
			del frappe.local.message_log[queued_messages:]
	if not readable:
		frappe.throw(_("This document is not available to you."), frappe.PermissionError)


def _due(user: str) -> list[frappe._dict]:
	"""The user's reminders that fell due within LISTED_FOR, the latest first, at most COUNT_CAP + 1."""
	now = now_datetime()
	return frappe.get_list(
		REMINDER,
		filters=[["user", "=", user], ["remind_at", "<=", now], ["remind_at", ">", now - LISTED_FOR]],
		fields=["name", "description", "remind_at", "reminder_doctype", "reminder_docname"],
		order_by="remind_at desc, name desc",
		limit_page_length=COUNT_CAP + 1,
		user=user,
	)


def _item(row: frappe._dict) -> dict:
	item = {"id": row.name, "title": row.description, "date": row.remind_at}
	if row.reminder_doctype and row.reminder_docname:
		item.update(
			reference_doctype=row.reminder_doctype,
			reference_name=row.reminder_docname,
			type_label=_(row.reminder_doctype),
		)
	else:
		item.update(reference_doctype=REMINDER, reference_name=row.name)
	return item
