# Copyright (c) 2026, Attention Center Contributors and contributors
# For license information, please see license.txt

"""Who acknowledged an announcement and who in its audience has not yet, for managers [FR-ANN-04].

The desk's report view adds the export. The report's roles and the report permission on the receipts already keep
other users out; execute checks the manager role too, as get_announcement_receipts does.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime

from attention_center.permissions import is_manager
from attention_center.sources import announcements


def execute(filters: dict | None = None) -> tuple:
	if not is_manager(frappe.session.user):
		frappe.throw(
			_("Only an Attention Manager can see who acknowledged an announcement."), frappe.PermissionError
		)
	name = (filters or {}).get("announcement")
	if not name:
		return _columns(), []
	# 0 for an announcement that asks for none; None for a missing one, which receipts() refuses.
	if frappe.db.get_value(announcements.ANNOUNCEMENT, name, "requires_acknowledgement") == 0:
		return _columns(), [], _("This announcement does not ask for an acknowledgement.")

	receipts = announcements.receipts(name)
	acknowledged = _("Acknowledged", context="Attention Center")
	awaiting = _("Awaiting acknowledgement")
	rows = [
		{
			"full_name": row["full_name"],
			"user": row["user"],
			"status": acknowledged,
			"acknowledged_at": get_datetime(row["acknowledged_at"]),
		}
		for row in receipts["acknowledged"]
	] + [
		{"full_name": row["full_name"], "user": row["user"], "status": awaiting}
		for row in receipts["pending"]
	]
	summary = [
		{
			"label": acknowledged,
			"value": len(receipts["acknowledged"]),
			"indicator": "Green",
			"datatype": "Int",
		},
		{"label": awaiting, "value": len(receipts["pending"]), "indicator": "Orange", "datatype": "Int"},
	]
	return _columns(), rows, None, None, summary


def _columns() -> list[dict]:
	# Frappe shows a script report's column labels as the server sends them. The context is a literal, which string
	# extraction needs.
	return [
		{
			"fieldname": "full_name",
			"label": _("Full Name", context="Attention Announcement Receipt"),
			"fieldtype": "Data",
			"width": 220,
		},
		{
			"fieldname": "user",
			"label": _("User", context="Attention Announcement Receipt"),
			"fieldtype": "Data",
			"width": 240,
		},
		{
			"fieldname": "status",
			"label": _("Status", context="Attention Announcement Receipt"),
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"fieldname": "acknowledged_at",
			"label": _("Acknowledged At", context="Attention Announcement Receipt"),
			"fieldtype": "Datetime",
			"width": 180,
		},
	]
