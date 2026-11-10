import frappe

SETTINGS = "Attention Center Settings"


def after_install() -> None:
	set_missing_settings_defaults()


def after_migrate() -> None:
	set_missing_settings_defaults()


def set_missing_settings_defaults() -> None:
	# A saved Single stores only the fields it had when saved, so a field added in a later
	# release would read as empty instead of its default on sites that saved their settings.
	stored = frappe.db.get_singles_dict(SETTINGS)
	missing = {
		df.fieldname: df.default
		for df in frappe.get_meta(SETTINGS).fields
		if df.default is not None and df.fieldname not in stored
	}
	if missing:
		frappe.db.set_single_value(SETTINGS, missing)
