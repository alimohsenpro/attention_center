# Copyright (c) 2026, Attention Center Contributors and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class AttentionAnnouncementReceipt(Document):
	pass


def on_doctype_update() -> None:
	"""Frappe runs this after syncing the DocType: one receipt per user and announcement, even when two requests
	race to store it [FR-ANN-03]."""
	frappe.db.add_unique("Attention Announcement Receipt", ("announcement", "user"))
