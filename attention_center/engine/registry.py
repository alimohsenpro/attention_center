"""Hook sources, their sync into Attention Source, and which sources a user sees (§4.6)."""

import json
import logging
import time

import frappe
from frappe.utils import cstr

from attention_center.engine.contract import ContractError, validate_source_def

SOURCE_DOCTYPE = "Attention Source"
VISIBLE_CACHE = "attention_center:visible"
VISIBLE_TTL_SECONDS = 300
KIND_OPTIONS = {"action": "Action", "info": "Info"}
SOURCE_TYPE_OPTIONS = {"doctype_query": "DocType Query", "python": "Python"}
MAPPED_FIELDS = {
	"title": "title_field",
	"from": "from_field",
	"date": "date_field",
	"priority": "priority_field",
	"due": "due_field",
	"status": "status_field",
}
SOURCE_FIELDS = (
	"key",
	"label",
	"kind",
	"source_type",
	"icon",
	"list_route",
	"reference_doctype",
	"filters_json",
	"priority_map_json",
	"recipient_fields",
	*MAPPED_FIELDS.values(),
	"get_count",
	"get_items",
	"get_recipients",
	"watch_doctypes",
)


def load_hook_sources() -> list[dict]:
	"""Valid `attention_sources` entries of every installed app, each with the declaring `app`.

	A rejected entry is logged once and skipped; the first app to declare a key keeps it.
	"""
	sources: dict[str, dict] = {}
	for app in frappe.get_installed_apps():
		for position, definition in enumerate(frappe.get_hooks("attention_sources", app_name=app), 1):
			try:
				validate_source_def(definition)
			except ContractError as error:
				_logger().error(f"{app}: attention_sources entry {position} skipped: {error}")
				continue

			key = definition["key"]
			if key in sources:
				_logger().error(
					f"{app}: attention_sources entry {position} skipped: key {key} is already declared by {sources[key]['app']}"
				)
				continue
			sources[key] = {**definition, "app": app}
	return list(sources.values())


def sync_sources() -> None:
	"""Upsert hook sources as system sources and disable the system sources no app declares any more."""
	synced = {source["key"] for source in load_hook_sources() if _sync_source(source)}

	# get_all: install/migrate code reviewing every system source, not a query made for a user.
	for key in frappe.get_all(SOURCE_DOCTYPE, filters={"is_system": 1, "enabled": 1}, pluck="name"):
		if key not in synced:
			frappe.db.set_value(SOURCE_DOCTYPE, key, "enabled", 0)
			_logger().warning(f"system source {key} disabled: no installed app declares a valid entry for it")

	clear_visibility_cache()


def _sync_source(source: dict) -> bool:
	key = source["key"]
	values = _definition_values(source)

	if frappe.db.exists(SOURCE_DOCTYPE, key):
		doc = frappe.get_doc(SOURCE_DOCTYPE, key)
		if not doc.is_system:
			_logger().error(
				f"{source['app']}: hook source {key} skipped: a source created in the desk uses this key"
			)
			return False
		if doc.label == doc.hook_label:
			values["label"] = source["label"]
		if not any(cstr(doc.get(fieldname)) != cstr(value) for fieldname, value in values.items()):
			return True
	else:
		doc = frappe.new_doc(SOURCE_DOCTYPE)
		values.update(key=key, label=source["label"])

	doc.update(values)
	doc.flags.from_hooks = True
	# The definition comes from an installed app's hooks and is applied by install/migrate code.
	doc.flags.ignore_permissions = True
	try:
		doc.save()
	except frappe.ValidationError as error:
		_logger().error(f"{source['app']}: hook source {key} skipped: {error}")
		return False
	return True


def _definition_values(source: dict) -> dict:
	"""Every definition field of Attention Source, so that a key removed from the hook entry is cleared."""
	fields = source.get("fields") or {}
	return {
		"is_system": 1,
		"app": source["app"],
		"hook_label": source["label"],
		"kind": KIND_OPTIONS[source["kind"]],
		"source_type": SOURCE_TYPE_OPTIONS[source["type"]],
		"icon": source.get("icon"),
		"list_route": source.get("list_route"),
		"reference_doctype": source.get("doctype"),
		"filters_json": _json(source.get("filters")),
		"priority_map_json": _json(source.get("priority_map")),
		"recipient_fields": _comma_separated(source.get("recipient_fields")),
		**{fieldname: fields.get(role) for role, fieldname in MAPPED_FIELDS.items()},
		"get_count": source.get("get_count"),
		"get_items": source.get("get_items"),
		"get_recipients": source.get("get_recipients"),
		"watch_doctypes": _comma_separated(source.get("watch_doctypes")),
	}


def get_visible_sources(user: str) -> list[frappe._dict]:
	"""Enabled sources the user is targeted by and, for DocType queries, may read; in display order.

	Cached per user for VISIBLE_TTL_SECONDS: role and group changes show up within that time, source and
	settings changes at once (clear_visibility_cache).
	"""
	cached = frappe.cache.hget(VISIBLE_CACHE, user)
	if cached and cached["expires_at"] > time.time():
		return cached["sources"]

	sources = _compute_visible_sources(user)
	frappe.cache.hset(
		VISIBLE_CACHE, user, {"expires_at": time.time() + VISIBLE_TTL_SECONDS, "sources": sources}
	)
	return sources


def clear_visibility_cache() -> None:
	_delete_visibility_cache()
	# A request reading the sources before this transaction commits would cache the old state again.
	frappe.db.after_commit.add(_delete_visibility_cache)


def _delete_visibility_cache() -> None:
	frappe.cache.delete_value(VISIBLE_CACHE)


def _compute_visible_sources(user: str) -> list[frappe._dict]:
	user_roles = set(frappe.get_roles(user))
	# get_all on configuration tables desk users cannot read; only the user's own memberships and the
	# sources that pass targeting and the DocType read check below come out of this function.
	user_groups = set(frappe.get_all("User Group Member", filters={"user": user}, pluck="parent"))
	target_roles = _targets("Attention Source Role", "role")
	target_groups = _targets("Attention Source User Group", "user_group")
	sources = frappe.get_all(
		SOURCE_DOCTYPE, filters={"enabled": 1}, fields=SOURCE_FIELDS, order_by="sort_order asc, creation asc"
	)

	return [
		source
		for source in sources
		if _is_targeted(target_roles.get(source.key), target_groups.get(source.key), user_roles, user_groups)
		and _can_read_records(source, user)
	]


def _targets(doctype: str, fieldname: str) -> dict[str, set[str]]:
	targets: dict[str, set[str]] = {}
	for row in frappe.get_all(doctype, filters={"parenttype": SOURCE_DOCTYPE}, fields=["parent", fieldname]):
		targets.setdefault(row.parent, set()).add(row[fieldname])
	return targets


def _is_targeted(
	roles: set[str] | None, groups: set[str] | None, user_roles: set[str], user_groups: set[str]
) -> bool:
	"""No targeting means every desk user; otherwise any listed role or any listed group is enough."""
	if not roles and not groups:
		return True
	return bool((roles or set()) & user_roles or (groups or set()) & user_groups)


def _can_read_records(source: frappe._dict, user: str) -> bool:
	if source.source_type != "DocType Query":
		return True
	try:
		return frappe.has_permission(source.reference_doctype, "read", user=user)
	except frappe.DoesNotExistError:
		# The DocType left with its app; the next migrate disables the source.
		return False


def _json(value: object) -> str | None:
	return None if value is None else json.dumps(value)


def _comma_separated(values: list[str] | None) -> str | None:
	return ", ".join(values) if values else None


def _logger() -> logging.Logger:
	return frappe.logger("attention_center")
