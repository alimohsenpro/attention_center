# Copyright (c) 2026, Attention Center Contributors and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from attention_center.engine.registry import clear_visibility_cache

BOUNDS = {
	"default_volume": (0, 100),
	"coalesce_seconds": (1, 120),
	"heartbeat_seconds": (60, 3600),
	"summary_cache_ttl": (5, 600),
	"page_size": (5, 50),
}
MIN_REMINDER_INTERVAL_HOURS = 0.25


class AttentionCenterSettings(Document):
	def validate(self) -> None:
		for fieldname, (low, high) in BOUNDS.items():
			if not low <= cint(self.get(fieldname)) <= high:
				frappe.throw(
					_("{0} must be between {1} and {2}.").format(self.field_label(fieldname), low, high)
				)

		interval = flt(self.reminder_interval_hours)
		if interval != 0 and interval < MIN_REMINDER_INTERVAL_HOURS:
			frappe.throw(
				_("{0} must be 0 (off) or at least {1}.").format(
					self.field_label("reminder_interval_hours"), MIN_REMINDER_INTERVAL_HOURS
				)
			)

	def on_update(self) -> None:
		clear_visibility_cache()

	def field_label(self, fieldname: str) -> str:
		return _(self.meta.get_label(fieldname), context=self.doctype)
