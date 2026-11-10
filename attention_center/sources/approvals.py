"""Built-in approvals source: documents waiting on the user's workflow action (§4.5)."""

from collections.abc import Iterator
from datetime import datetime
from itertools import islice

import frappe
from frappe import _
from frappe.model.document import Document

from attention_center.engine.contract import COUNT_CAP


def get_count(user: str, since: datetime | None = None) -> dict:
	"""Documents waiting on the user; every one is new to a user without a watermark (`since`)."""
	dates = [action.creation for action, _document in _pending(user)]
	return {
		"count": len(dates),
		"latest": max(dates, default=None),
		"new_since": len(dates) if since is None else sum(date > since for date in dates),
	}


def get_items(user: str, start: int, page_length: int) -> list[dict]:
	"""One page of the documents waiting on the user, newest action first."""
	return [
		_item(action, document) for action, document in islice(_pending(user), start, start + page_length)
	]


def _pending(user: str) -> Iterator[tuple[frappe._dict, Document]]:
	"""Open actions among the newest COUNT_CAP + 1, one per document, on documents the user may read.

	Workflow Action's permission_query_conditions keep the actions of the user's roles but do not look at the
	document, so read permission is checked on each one [FR-PERM-03]. Lazy, so that a page stops checking
	once it is full. Deleting a document or a DocType leaves its actions behind; those actions are skipped.
	"""
	actions = frappe.get_list(
		"Workflow Action",
		filters={"status": "Open"},
		fields=["name", "reference_doctype", "reference_name", "workflow_state", "creation"],
		order_by="creation desc, name desc",
		limit_page_length=COUNT_CAP + 1,
		user=user,
	)
	seen = set()
	doctype_exists = {}
	for action in actions:
		doctype, name = action.reference_doctype, action.reference_name
		if (doctype, name) in seen:
			continue
		seen.add((doctype, name))
		# get_doc on a deleted DocType raises ImportError, not DoesNotExistError, so it is checked first.
		if doctype not in doctype_exists:
			doctype_exists[doctype] = bool(frappe.db.exists("DocType", doctype))
		if not doctype_exists[doctype]:
			continue
		document = _readable_document(doctype, name, user)
		if document:
			yield action, document


def _readable_document(doctype: str, name: str, user: str) -> Document | None:
	queued_messages = len(frappe.local.message_log)
	try:
		document = frappe.get_doc(doctype, name)
	except frappe.DoesNotExistError:
		# Drop the "not found" message frappe.throw queued, or the background refresh would show it to the user.
		del frappe.local.message_log[queued_messages:]
		return None
	return document if frappe.has_permission(doctype, "read", document, user=user) else None


def _item(action: frappe._dict, document: Document) -> dict:
	return {
		"id": action.name,
		"title": _title(document),
		"reference_doctype": document.doctype,
		"reference_name": document.name,
		"type_label": _(document.doctype),
		"date": action.creation,
		"status_label": _(action.workflow_state) if action.workflow_state else None,
	}


def _title(document: Document) -> str:
	"""The value of the title field when the user may read that field, else the document name."""
	name = str(document.name)
	df = document.meta.get_field(document.meta.get_title_field())
	if df and document.has_permlevel_access_to(df.fieldname, df):
		return str(document.get(df.fieldname) or name)
	return name
