"""Built-in announcements source, acknowledgements and receipts (§3.4, §4.5).

A desk user receives an announcement while it is published, inside its validity window and addressed to them:
to every desk user, or to a role they hold, or to a user group they belong to [FR-ANN-01]. `received` is that
rule. It is also the read permission of Attention Announcement for everyone but the managers (the DocType's
permission hooks call it), and the source applies it to the managers too: they may read every announcement, but
receive only the ones addressed to them.
"""

from datetime import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Order
from frappe.utils import cstr, get_fullname, now_datetime

from attention_center.engine import realtime
from attention_center.engine.contract import COUNT_CAP

KEY = "attention_center.announcements"
ANNOUNCEMENT = "Attention Announcement"
RECEIPT = "Attention Announcement Receipt"
ROLE_TARGET = "Attention Source Role"
GROUP_TARGET = "Attention Source User Group"
PRIORITY_RANK = {"Immediate": 0, "Urgent": 1, "Normal": 2}


def get_count(user: str, since: datetime | None = None) -> dict:
	"""Announcements awaiting the user's acknowledgement are their action items; any received one can be new."""
	rows = received(user)
	waiting = [row for row in rows if awaits_acknowledgement(row)]
	return {
		"count": len(waiting),
		"urgent": sum(row.priority == "Urgent" for row in waiting),
		"immediate": sum(row.priority == "Immediate" for row in waiting),
		"latest": rows[0].valid_from if rows else None,
		"new_since": len(rows) if since is None else sum(row.valid_from > since for row in rows),
	}


def get_items(user: str, start: int, page_length: int) -> list[dict]:
	"""Those awaiting acknowledgement first, then by priority; the sort is stable, so newest first within each."""
	rows = sorted(
		received(user), key=lambda row: (not awaits_acknowledgement(row), PRIORITY_RANK[row.priority])
	)
	return [_item(row) for row in rows[start : start + page_length]]


def received(user: str, name: str | None = None) -> list[frappe._dict]:
	"""The announcements the user receives now, or the one named, with the user's `acknowledged_at`.

	Newest first and at most COUNT_CAP + 1, like the rows every source counts. None without read permission on
	the DocType, so that a site withdrawing it hides announcements instead of listing what cannot be opened.
	"""
	if not frappe.has_permission(ANNOUNCEMENT, "read", user=user):
		return []

	announcement = frappe.qb.DocType(ANNOUNCEMENT)
	receipt = frappe.qb.DocType(RECEIPT)
	role_target = frappe.qb.DocType(ROLE_TARGET)
	group_target = frappe.qb.DocType(GROUP_TARGET)
	member = frappe.qb.DocType("User Group Member")
	now = now_datetime()
	by_role = (
		frappe.qb.from_(role_target)
		.select(role_target.parent)
		.where((role_target.parenttype == ANNOUNCEMENT) & role_target.role.isin(frappe.get_roles(user)))
	)
	by_group = (
		frappe.qb.from_(group_target)
		.join(member)
		.on(member.parent == group_target.user_group)
		.select(group_target.parent)
		.where((group_target.parenttype == ANNOUNCEMENT) & (member.user == user))
	)
	# A query of its own rather than frappe.get_list: this is the rule the DocType's permission hooks apply, and
	# get_list exempts the managers from it. The user's own receipt comes along; nobody else's is read.
	query = (
		frappe.qb.from_(announcement)
		.left_join(receipt)
		.on((receipt.announcement == announcement.name) & (receipt.user == user))
		.select(
			announcement.name,
			announcement.title,
			announcement.priority,
			announcement.valid_from,
			announcement.requires_acknowledgement,
			announcement.owner,
			receipt.acknowledged_at,
		)
		.where(announcement.published == 1)
		.where(announcement.valid_from <= now)
		.where(announcement.valid_to.isnull() | (announcement.valid_to > now))
		.where(
			(announcement.all_users == 1) | announcement.name.isin(by_role) | announcement.name.isin(by_group)
		)
		.orderby(announcement.valid_from, order=Order.desc)
		.orderby(announcement.name, order=Order.desc)
		.limit(COUNT_CAP + 1)
	)
	if name is not None:
		query = query.where(announcement.name == name)
	return query.run(as_dict=True)


def awaits_acknowledgement(row: frappe._dict) -> bool:
	return bool(row.requires_acknowledgement) and not row.acknowledged_at


def acknowledge(name: str) -> datetime:
	"""Store the session user's acknowledgement of an announcement they receive, once [FR-ANN-03].

	Returns when they acknowledged it: now, or at their earlier acknowledgement.
	"""
	user = frappe.session.user
	rows = received(user, name)
	if not rows:
		# The same answer for an announcement that does not exist, so that it tells nothing about the others.
		frappe.throw(_("This announcement is not available to you."), frappe.PermissionError)
	if not rows[0].requires_acknowledgement:
		frappe.throw(_("This announcement does not ask for an acknowledgement."))
	if rows[0].acknowledged_at:
		return rows[0].acknowledged_at

	receipt = frappe.new_doc(RECEIPT, announcement=name, user=user, acknowledged_at=now_datetime())
	queued_messages = len(frappe.local.message_log)
	try:
		# Users cannot create receipts in the desk: this is the session user's own, for an announcement they receive.
		receipt.insert(ignore_permissions=True)
	except frappe.UniqueValidationError:
		# A parallel request of the same user stored it first, and the unique index keeps one receipt.
		del frappe.local.message_log[queued_messages:]
		# A locking read sees the row the other transaction committed after this one began reading.
		return frappe.db.get_value(
			RECEIPT, {"announcement": name, "user": user}, "acknowledged_at", for_update=True
		)
	# The user's other tabs drop the announcement from their action items.
	realtime.nudge([user], KEY)
	return receipt.acknowledged_at


def receipts(name: str) -> dict:
	"""Who acknowledged the announcement and when, and who in its audience has not yet [FR-ANN-04].

	For managers only: the caller checks the role.
	"""
	announcement = frappe.get_doc(ANNOUNCEMENT, name)
	acknowledged = frappe.get_list(
		RECEIPT,
		filters={"announcement": name},
		fields=["user", "acknowledged_at"],
		order_by="acknowledged_at asc, user asc",
		limit_page_length=0,
	)
	addressed = audience(announcement)
	full_names = {user.name: user.full_name for user in addressed}
	done = {row.user for row in acknowledged}
	return {
		"acknowledged": [
			{
				"user": row.user,
				# Someone who acknowledged may have left the audience since.
				"full_name": full_names.get(row.user) or get_fullname(row.user),
				"acknowledged_at": row.acknowledged_at.isoformat(timespec="seconds"),
			}
			for row in acknowledged
		],
		"pending": [
			{"user": user.name, "full_name": user.full_name} for user in addressed if user.name not in done
		],
	}


def audience(announcement: Document) -> list[frappe._dict]:
	"""The enabled desk users the announcement is addressed to, with their full names, ordered by full name."""
	# get_all: a manager's view of whom an announcement addresses, and Attention Managers need not read User.
	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User"},
		fields=["name", "full_name"],
		order_by="full_name asc, name asc",
	)
	if announcement.all_users:
		return users

	addressed = set()
	roles = [row.role for row in announcement.roles]
	if roles:
		addressed.update(
			frappe.get_all("Has Role", filters={"parenttype": "User", "role": ("in", roles)}, pluck="parent")
		)
	groups = [row.user_group for row in announcement.user_groups]
	if groups:
		addressed.update(
			frappe.get_all("User Group Member", filters={"parent": ("in", groups)}, pluck="user")
		)
	return [user for user in users if user.name in addressed]


def _item(row: frappe._dict) -> dict:
	item = {
		"id": row.name,
		"title": row.title,
		"reference_doctype": ANNOUNCEMENT,
		"reference_name": row.name,
		"type_label": _("Announcement", context="Attention Center"),
		"from_user": row.owner,
		"date": row.valid_from,
		"priority": cstr(row.priority).lower(),
	}
	if awaits_acknowledgement(row):
		item.update(status_label=_("Awaiting acknowledgement"), status_color="orange")
	elif row.acknowledged_at:
		item.update(status_label=_("Acknowledged", context="Attention Center"), status_color="green")
	return item
