"""Who manages the Attention Center [FR-SET-03]."""

import frappe

MANAGER_ROLES = frozenset(("System Manager", "Attention Manager"))


def is_manager(user: str) -> bool:
	# frappe.only_for lets everyone through while tests run, so a test could not prove a check made with it.
	return bool(MANAGER_ROLES & set(frappe.get_roles(user)))
