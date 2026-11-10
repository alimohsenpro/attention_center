import frappe

from attention_center.engine.registry import sync_sources

SETTINGS = "Attention Center Settings"


def after_install() -> None:
	sync_sources()


def after_migrate() -> None:
	set_missing_settings_defaults()
	sync_sources()


def set_missing_settings_defaults() -> None:
	# Frappe stores a Single's defaults once, at install. A settings field added by a later release
	# has no stored value on existing sites and would read as empty instead of its default.
	stored = frappe.db.get_singles_dict(SETTINGS)
	missing = {
		df.fieldname: df.default
		for df in frappe.get_meta(SETTINGS).fields
		if df.default is not None and df.fieldname not in stored
	}
	if missing:
		frappe.db.set_single_value(SETTINGS, missing)
