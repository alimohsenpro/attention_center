"""Content-free nudges, sent after commit, to the users a change concerns (§6).

A nudge only tells a browser to refresh its summary [FR-PERM-05]: user nudges carry the source keys and the
actor, broadcasts the source keys and `broadcast`.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, escape_html

from attention_center.engine import recipients, registry, runner

EVENT = "attention_center_nudge"
PENDING = "attention_center_nudges"


@dataclass
class _Pending:
	"""The nudges of the current transaction."""

	pairs: set[tuple[str, str]] = field(default_factory=set)
	broadcast: set[str] = field(default_factory=set)


def on_doc_event(doc: Document, method: str | None = None) -> None:
	"""doc_events handler (on_change, on_trash) of every DocType [FR-RT-01].

	A DocType no enabled source watches costs one dict lookup [FR-RT-01 AC1]. Never raises: a failure here must
	not stop the user's save.
	"""
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_import:
		return
	try:
		sources = registry.get_watch_map().get(doc.doctype)
		if sources:
			_queue_document(doc, sources, method)
	except Exception as error:
		_logger().error(f"nudges for a {doc.doctype} change failed: {type(error).__name__}")


def nudge(users: list[str], source_key: str) -> None:
	"""Nudge `users` about the source `source_key` once the current transaction commits [FR-RT-03].

	For a consumer app's change that raises no document event, such as a scheduler job's. More than
	recipients.AUDIENCE_CAP users get one site-wide broadcast instead.
	"""
	if not isinstance(source_key, str) or not frappe.db.exists(registry.SOURCE_DOCTYPE, source_key):
		frappe.throw(_("{0} is not an Attention Center source.").format(escape_html(cstr(source_key))))
	if not isinstance(users, list | tuple | set) or not all(isinstance(user, str) for user in users):
		frappe.throw(_("Users to nudge must be a list of user ids."))
	_queue(recipients.audience(users), source_key)


def _queue_document(doc: Document, sources: list[frappe._dict], method: str | None) -> None:
	for source in sources:
		_queue(recipients.get_recipients(source, doc, method), source.key)


def _queue(users: list[str] | None, source_key: str) -> None:
	"""Add to the transaction's nudges. None stands for an audience too large or unknown: a broadcast."""
	pending = _pending()
	if users is None:
		pending.broadcast.add(source_key)
	else:
		pending.pairs.update((user, source_key) for user in users)


def _pending() -> _Pending:
	pending = getattr(frappe.local, PENDING, None)
	if pending is None:
		pending = _Pending()
		setattr(frappe.local, PENDING, pending)
		# One callback per transaction however many changes it holds [FR-RT-01 AC2].
		frappe.db.after_commit.add(_send)
		frappe.db.after_rollback.add(_discard)
	return pending


def _discard() -> None:
	if hasattr(frappe.local, PENDING):
		delattr(frappe.local, PENDING)


def _send() -> None:
	"""after_commit callback: deliver the transaction's nudges."""
	pending = getattr(frappe.local, PENDING, None)
	_discard()
	if pending is None:
		return
	# Runs after the commit: an exception would reach the request whose changes are already saved.
	try:
		_publish(pending)
	except Exception as error:
		_logger().error(f"sending nudges failed: {type(error).__name__}")


def _publish(pending: _Pending) -> None:
	"""Drop the cached counts the transaction changed, then nudge each user once and the site at most once.

	The actor in a user nudge lets the actor's own browser stay quiet (FR-ALERT-04). A broadcast names no
	actor, since every desk user receives it; its sources are left out of the user nudges.
	"""
	sources_by_user: dict[str, list[str]] = defaultdict(list)
	for user, key in sorted(pending.pairs):
		if key not in pending.broadcast:
			sources_by_user[user].append(key)

	for key in pending.broadcast:
		frappe.cache.delete_value(runner.COUNT_CACHE.format(key))
	for user, keys in sources_by_user.items():
		for key in keys:
			frappe.cache.hdel(runner.COUNT_CACHE.format(key), user)

	actor = frappe.session.user
	for user, keys in sources_by_user.items():
		frappe.publish_realtime(EVENT, {"sources": keys, "actor": actor}, user=user)
	if pending.broadcast:
		frappe.publish_realtime(EVENT, {"sources": sorted(pending.broadcast), "broadcast": True})


def _logger() -> logging.Logger:
	return frappe.logger("attention_center")
