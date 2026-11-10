"""Who to nudge when a document of a watched DocType changes (§6)."""

import logging
from collections.abc import Iterable

import frappe
from frappe.model.document import Document
from frappe.model.workflow import get_workflow_name
from frappe.permissions import ALL_USER_ROLE, GUEST_ROLE, SYSTEM_USER_ROLE

from attention_center.sources.builtin import APPROVALS

# Above this many users the nudge goes to the whole site, content-free, instead of to each user's room.
AUDIENCE_CAP = 200
# Frappe gives these roles without a Has Role row, so their holders cannot be listed.
IMPLICIT_ROLES = frozenset((GUEST_ROLE, ALL_USER_ROLE, SYSTEM_USER_ROLE))


def get_recipients(source: frappe._dict, doc: Document, method: str | None) -> list[str] | None:
	"""The users whose counts of `source` the change of `doc` (document event `method`) may move.

	None when they cannot be listed or are more than AUDIENCE_CAP: the caller then nudges the whole site.
	`source` is an entry of registry.get_watch_map(). Runs in the actor's request, as the actor.
	"""
	if source.key == APPROVALS["key"]:
		return _approvers(doc, method)
	if source.source_type == "Python":
		return _from_callable(source, doc)
	return _from_fields(source, doc)


def audience(users: Iterable[object]) -> list[str] | None:
	"""The distinct user ids among `users`, or None when they are more than AUDIENCE_CAP."""
	distinct = sorted({user for user in users if isinstance(user, str) and user})
	return distinct if len(distinct) <= AUDIENCE_CAP else None


def _from_fields(source: frappe._dict, doc: Document) -> list[str] | None:
	"""The values of the recipient fields before and after the change, so a reassignment nudges both users."""
	if not source.recipient_fields:
		return None
	versions = [version for version in (doc, doc.get_doc_before_save()) if version]
	return audience(version.get(fieldname) for version in versions for fieldname in source.recipient_fields)


def _from_callable(source: frappe._dict, doc: Document) -> list[str] | None:
	if not source.get_recipients:
		return None

	queued_messages = len(frappe.local.message_log)
	try:
		users = frappe.get_attr(source.get_recipients)(doc)
	except Exception as error:
		# A message the function queued would open a dialog in the actor's save; the document may be quoted
		# in an exception message, so only its type is logged [NFR-PRIV-01].
		del frappe.local.message_log[queued_messages:]
		_logger().error(
			f"source {source.key}: get_recipients failed for a {doc.doctype} change: {type(error).__name__}"
		)
		return None

	if not isinstance(users, list | tuple | set):
		_logger().error(
			f"source {source.key}: get_recipients returned {type(users).__name__} instead of a list of user ids"
		)
		return None
	return audience(users)


def _approvers(doc: Document, method: str | None) -> list[str] | None:
	"""Holders of the roles whose open Workflow Actions the change creates, completes or deletes (§4.5)."""
	if doc.doctype == "Workflow Action":
		versions = [version for version in (doc, doc.get_doc_before_save()) if version]
		return _role_holders({row.role for version in versions for row in version.permitted_roles})
	return _role_holders(_roles_of_left_state(doc, method))


def _roles_of_left_state(doc: Document, method: str | None) -> set[str]:
	"""The roles allowed to act on the workflow state `doc` leaves, by a transition or by being deleted.

	Frappe completes or deletes the open action of that state with a query, and has done so before this app's
	handler runs, so the roles come from the workflow definition. An insert or a save that keeps the state
	leaves none: the actions it creates nudge their own role holders.
	"""
	workflow_name = get_workflow_name(doc.doctype)
	if not workflow_name:
		# Deactivated after this request read the watch map.
		return set()
	workflow = frappe.get_cached_doc("Workflow", workflow_name)
	state = doc.get(workflow.workflow_state_field)
	if method != "on_trash":
		before = doc.get_doc_before_save()
		if not before or before.get(workflow.workflow_state_field) == state:
			return set()
		state = before.get(workflow.workflow_state_field)
	return {transition.allowed for transition in workflow.transitions if transition.state == state}


def _role_holders(roles: set[str]) -> list[str] | None:
	if roles & IMPLICIT_ROLES:
		return None
	if not roles:
		return []

	# get_all: role holders only choose the user rooms a content-free nudge goes to; nobody sees the list.
	holders = frappe.get_all(
		"User",
		filters=[["Has Role", "role", "in", sorted(roles)], ["enabled", "=", 1]],
		pluck="name",
		distinct=True,
		limit=AUDIENCE_CAP + 1,
	)
	return audience(holders)


def _logger() -> logging.Logger:
	return frappe.logger("attention_center")
