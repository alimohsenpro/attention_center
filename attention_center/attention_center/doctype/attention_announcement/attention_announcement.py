# Copyright (c) 2026, Attention Center Contributors and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime
from frappe.utils.html_utils import sanitize_html

from attention_center.engine.recipients import IMPLICIT_ROLES
from attention_center.permissions import is_manager
from attention_center.sources import announcements


class AttentionAnnouncement(Document):
	def validate(self) -> None:
		# Frappe sanitises a Text Editor too, unless a customisation sets "Ignore XSS Filter" [NFR-SEC-03].
		self.body = sanitize_html(self.body, linkify=True, always_sanitize=True)
		self.validate_roles()
		if self.published:
			self.validate_audience()
			self.start_at_publishing()
		self.validate_window()

	def validate_roles(self) -> None:
		# Frappe gives these roles without a Has Role row: nobody could tell who received the announcement.
		implicit = sorted({row.role for row in self.roles} & IMPLICIT_ROLES)
		if implicit:
			frappe.throw(
				_("{0} is given to every user. Tick {1} instead.").format(
					", ".join(implicit), self.field_label("all_users")
				)
			)

	def validate_audience(self) -> None:
		if not (self.all_users or self.roles or self.user_groups):
			frappe.throw(
				_("Choose who receives the announcement: {0}, {1} or {2}.").format(
					self.field_label("all_users"), self.field_label("roles"), self.field_label("user_groups")
				)
			)

	def start_at_publishing(self) -> None:
		"""An announcement cannot have arrived before it was published: its date, and what counts as new to a
		user, start then."""
		before = self.get_doc_before_save()
		if before and before.published:
			return
		now = now_datetime()
		if not self.valid_from or get_datetime(self.valid_from) < now:
			self.valid_from = now

	def validate_window(self) -> None:
		if self.valid_from and self.valid_to and get_datetime(self.valid_to) <= get_datetime(self.valid_from):
			frappe.throw(
				_("{0} must be later than {1}.").format(
					self.field_label("valid_to"), self.field_label("valid_from")
				)
			)

	def field_label(self, fieldname: str) -> str:
		return _(self.meta.get_label(fieldname), context=self.doctype)


def get_permission_query_conditions(user: str | None = None) -> str:
	"""permission_query_conditions hook: a manager lists every announcement, anyone else those they receive now."""
	user = user or frappe.session.user
	if is_manager(user):
		return ""
	names = [frappe.db.escape(row.name) for row in announcements.received(user)] or ["''"]
	return f"`tab{announcements.ANNOUNCEMENT}`.`name` in ({', '.join(names)})"


def has_permission(doc: Document, ptype: str | None = None, user: str | None = None) -> bool:
	"""has_permission hook: anyone but a manager may open an announcement only while they receive it.

	Hooks can only deny: what a user may do with an announcement still comes from the DocType's permissions.
	"""
	user = user or frappe.session.user
	return is_manager(user) or bool(doc.name and announcements.received(user, doc.name))
