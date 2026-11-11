"""The sample app's python source for Attention Center: the unassigned open requests of the user's teams.

Attention Center calls these functions by the dotted paths in hooks.py (docs/PROVIDER_CONTRACT.md). This
module never imports attention_center, so the app works the same on a site without it.
"""

from datetime import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

DOCTYPE = "Sample Request"
# Attention Center shows counts up to 99 and reads 100 rows to know that there are more.
LIMIT = 100
PRIORITIES = {"High": "urgent", "Critical": "immediate"}
URGENCY = ("immediate", "urgent", "normal")


def team_queue_count(user: str, since: datetime | None = None) -> dict:
	"""The queue's counters. `since` is when the user last looked at the queue, None if they never did."""
	requests = _team_queue(user)
	priorities = [_priority(request) for request in requests]
	dates = [request.creation for request in requests]
	return {
		"count": len(requests),
		"urgent": priorities.count("urgent"),
		"immediate": priorities.count("immediate"),
		"overdue": sum(_is_overdue(request) for request in requests),
		"latest": max(dates, default=None),
		"new_since": len(dates) if since is None else sum(date > since for date in dates),
	}


def team_queue_items(user: str, start: int, page_length: int) -> list[dict]:
	"""One page of the queue: overdue first, then immediate, urgent and normal, newest first within each."""
	requests = sorted(_team_queue(user), key=_urgency)
	return [_item(request) for request in requests[start : start + page_length]]


def team_queue_recipients(doc: Document) -> list[str]:
	"""The members of the request's team before and after the change: both queues may have changed.

	Runs in the request of whoever changed the document, so it must not depend on frappe.session.user.
	"""
	before = doc.get_doc_before_save()
	teams = {team for team in (doc.team, before and before.team) if team}
	if not teams:
		return []
	# get_all: these users only receive a nudge without content; nobody is shown the list.
	return frappe.get_all(
		"User Group Member",
		filters={"parenttype": "User Group", "parent": ["in", sorted(teams)]},
		pluck="user",
	)


def nudge_attention_center(users: list[str], source_key: str) -> None:
	"""Refresh what `users` see of a source after a change that raises no document event.

	For example a scheduled job that updates requests with frappe.db.set_value. Does nothing on a site
	without Attention Center.
	"""
	if "attention_center" in frappe.get_installed_apps():
		frappe.get_attr("attention_center.engine.realtime.nudge")(users, source_key)


def _team_queue(user: str) -> list[frappe._dict]:
	"""The newest LIMIT unassigned open requests of the user's teams that the user may read, newest first."""
	# Attention Center does not check a python source's DocType: a user who may not read requests gets an
	# empty queue, where raising would show the tab as failed.
	if not frappe.has_permission(DOCTYPE, "read", user=user):
		return []
	teams = _teams(user)
	if not teams:
		return []
	# get_list applies the user's role permissions, user permissions and permission query conditions.
	return frappe.get_list(
		DOCTYPE,
		filters={"status": "Open", "assigned_to": ["is", "not set"], "team": ["in", teams]},
		fields=["name", "subject", "owner", "creation", "priority", "due_date", "team"],
		order_by="creation desc, name desc",
		limit_page_length=LIMIT,
		user=user,
	)


def _teams(user: str) -> list[str]:
	# get_all: the user's own memberships, which a desk user may not read through get_list.
	return frappe.get_all(
		"User Group Member", filters={"parenttype": "User Group", "user": user}, pluck="parent"
	)


def _item(request: frappe._dict) -> dict:
	return {
		"id": request.name,
		"title": request.subject or request.name,
		"reference_doctype": DOCTYPE,
		"reference_name": request.name,
		"type_label": request.team,
		"from_user": request.owner,
		"date": request.creation,
		"priority": _priority(request),
		"due": request.due_date,
		"status_label": _("Unassigned"),
		"status_color": "orange",
	}


def _priority(request: frappe._dict) -> str:
	return PRIORITIES.get(request.priority, "normal")


def _is_overdue(request: frappe._dict) -> bool:
	# A due date is overdue from the next day on, as Attention Center computes it for the items.
	return bool(request.due_date) and getdate(request.due_date) < getdate()


def _urgency(request: frappe._dict) -> tuple[bool, int]:
	return not _is_overdue(request), URGENCY.index(_priority(request))
