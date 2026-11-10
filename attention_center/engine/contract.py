"""Source contract v1: the hook entries apps declare and the items their sources return (§4.1 to §4.3)."""

import html
import json
import re
from collections.abc import Callable
from datetime import date, datetime
from typing import TypedDict
from zoneinfo import ZoneInfo

import frappe
from frappe.desk.utils import slug
from frappe.utils import get_fullname, get_system_timezone, getdate, now_datetime, quoted, strip_html

CONTRACT_VERSION = 1
SUPPORTED_CONTRACT_VERSIONS = (CONTRACT_VERSION,)

KEY_PATTERN = re.compile(r"[a-z0-9_]+(\.[a-z0-9_]+)+")
DOTTED_PATH_PATTERN = re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)+")
DESK_ROUTE_PREFIX = "/app/"
KINDS = ("action", "info")
SOURCE_TYPES = ("doctype_query", "python")
PRIORITIES = ("normal", "urgent", "immediate")
STATUS_COLORS = ("gray", "blue", "green", "orange", "red")
FIELD_ROLES = ("title", "from", "date", "priority", "due", "status")
REQUIRED_FIELD_ROLES = ("title", "date")
TITLE_MAX_LENGTH = 200
# Counts are capped so that every source costs one query of at most COUNT_CAP + 1 rows (T-07).
COUNT_CAP = 99
COUNTERS = ("urgent", "immediate", "overdue", "new_since")

COMMON_KEYS = frozenset(("key", "contract_version", "label", "kind", "type", "icon", "list_route"))
TYPE_KEYS = {
	"doctype_query": frozenset(("doctype", "fields", "filters", "priority_map", "recipient_fields")),
	"python": frozenset(("get_count", "get_items", "get_recipients", "watch_doctypes")),
}


class ContractError(frappe.ValidationError):
	"""A hook entry or a source's output does not follow the source contract.

	The message is for the source's developer and goes to the log only, so it is not translated.
	"""


class Item(TypedDict):
	id: str
	title: str
	route: str
	type_label: str | None
	from_label: str | None
	date: str | None
	priority: str
	due: str | None
	overdue: bool
	status_label: str | None
	status_color: str


class Counts(TypedDict):
	count: int
	capped: bool
	urgent: int
	immediate: int
	overdue: int
	latest: str | None
	new_since: int


def validate_source_def(definition: object) -> None:
	"""Raise ContractError naming the first rule a hook entry breaks.

	Filters, the priority map and fieldnames are checked against the DocType by the Attention Source
	controller when the sync saves the entry, so the rules live in one place. Here filters and the priority
	map are only checked to hold values the sync can store as JSON.
	"""
	if not isinstance(definition, dict):
		raise ContractError("the entry is not a dict")

	version = definition.get("contract_version")
	if type(version) is not int or version not in SUPPORTED_CONTRACT_VERSIONS:
		raise ContractError(
			f"contract_version {version!r} is not supported; supported: {SUPPORTED_CONTRACT_VERSIONS}"
		)
	if not isinstance(definition.get("key"), str) or not KEY_PATTERN.fullmatch(definition["key"]):
		raise ContractError("key must look like app.identifier (lowercase letters, digits, underscores)")

	source_type = definition.get("type")
	if source_type not in SOURCE_TYPES:
		raise ContractError(f"type must be one of {SOURCE_TYPES}")
	unknown = set(definition) - COMMON_KEYS - TYPE_KEYS[source_type]
	if unknown:
		raise ContractError(f"unknown keys for type {source_type}: {', '.join(sorted(map(str, unknown)))}")

	if not _is_text(definition.get("label")):
		raise ContractError("label must be non-empty text")
	if definition.get("kind") not in KINDS:
		raise ContractError(f"kind must be one of {KINDS}")
	if not _is_optional(definition, "icon", _is_text):
		raise ContractError("icon must be non-empty text")
	if not _is_optional(definition, "list_route", is_desk_route):
		raise ContractError(f"list_route must start with {DESK_ROUTE_PREFIX}")

	if source_type == "doctype_query":
		_validate_query_def(definition)
	else:
		_validate_python_def(definition)


def _validate_query_def(definition: dict) -> None:
	if not _is_text(definition.get("doctype")):
		raise ContractError("doctype must name a DocType")

	fields = definition.get("fields")
	if not isinstance(fields, dict):
		raise ContractError(f"fields must map {', '.join(FIELD_ROLES)} to fieldnames")
	unknown = set(fields) - set(FIELD_ROLES)
	if unknown:
		raise ContractError(f"unknown fields roles: {', '.join(sorted(map(str, unknown)))}")
	missing = [role for role in REQUIRED_FIELD_ROLES if role not in fields]
	if missing:
		raise ContractError(f"fields must map {', '.join(missing)}")
	if not all(_is_text(fieldname) for fieldname in fields.values()):
		raise ContractError("every mapped fieldname must be non-empty text")

	if not _is_optional(definition, "filters", lambda value: isinstance(value, list)):
		raise ContractError("filters must be a list of [field, operator, value] conditions")
	if not _is_optional(definition, "priority_map", lambda value: isinstance(value, dict)):
		raise ContractError("priority_map must be a dict")
	for name in ("filters", "priority_map"):
		if not _is_json(definition.get(name)):
			raise ContractError(
				f"{name} must hold only JSON values: text, numbers, booleans, None, lists and dicts"
			)
	if not _is_optional(definition, "recipient_fields", _is_text_list):
		raise ContractError("recipient_fields must be a list of fieldnames")


def _validate_python_def(definition: dict) -> None:
	for name in ("get_count", "get_items"):
		if not _is_dotted_path(definition.get(name)):
			raise ContractError(f"{name} must be the dotted path of a function")
	if not _is_optional(definition, "get_recipients", _is_dotted_path):
		raise ContractError("get_recipients must be the dotted path of a function")
	if not _is_optional(definition, "watch_doctypes", _is_text_list):
		raise ContractError("watch_doctypes must be a list of DocType names")


def normalize_items(source_key: str, items: object) -> list[Item]:
	"""Normalise the items a source returned, dropping the ones that break the contract.

	Logs one warning per call with the source key and counts only: item content never reaches the log.
	"""
	if not isinstance(items, list):
		raise ContractError(f"source {source_key} returned {type(items).__name__} instead of a list of items")

	normalized: list[Item] = []
	seen_ids = set()
	for raw in items:
		item = normalize_item(raw)
		if item and item["id"] not in seen_ids:
			seen_ids.add(item["id"])
			normalized.append(item)

	dropped = len(items) - len(normalized)
	if dropped:
		frappe.logger("attention_center").warning(
			f"source {source_key}: dropped {dropped} of {len(items)} items without a valid id, title or route, or with a repeated id"
		)
	return normalized


def normalize_count(result: object) -> Counts:
	"""Normalise what a source's count returned: a whole number, or a dict with `count` and optional counters.

	Every number is capped at COUNT_CAP and `capped` tells whether `count` was. A value of the wrong type
	breaks the contract: unlike an item's label, a count has no harmless default to fall back to.
	"""
	if _is_whole_number(result):
		result = {"count": result}
	if not isinstance(result, dict) or not _is_whole_number(result.get("count")):
		raise ContractError("the count must be a whole number of at least 0, or a dict holding one in count")

	counters = {name: result.get(name) or 0 for name in COUNTERS}
	invalid = [name for name, value in counters.items() if not _is_whole_number(value)]
	if invalid:
		raise ContractError(f"{', '.join(invalid)} must be whole numbers of at least 0")
	latest = parse_when(result.get("latest"))
	if result.get("latest") and latest is None:
		raise ContractError("latest must be a date, a datetime or ISO text")

	return {
		"count": min(result["count"], COUNT_CAP),
		"capped": result["count"] > COUNT_CAP,
		**{name: min(value, COUNT_CAP) for name, value in counters.items()},
		"latest": _iso(latest),
	}


def normalize_item(raw: object) -> Item | None:
	"""Return the item in its normalised shape, or None if it lacks a valid id, title or route.

	An invalid optional value falls back to its default: the item stays openable and is not lost.
	"""
	if not isinstance(raw, dict):
		return None

	item_id = _item_id(raw.get("id"))
	title = _plain_text(raw.get("title"))
	route = _item_route(raw)
	if not (item_id and title and route):
		return None

	due = parse_when(raw.get("due"))
	return {
		"id": item_id,
		"title": title[:TITLE_MAX_LENGTH],
		"route": route,
		"type_label": _text(raw.get("type_label")),
		"from_label": _text(raw.get("from_label")) or _full_name(raw.get("from_user")),
		"date": _iso(parse_when(raw.get("date"))),
		"priority": _choice(raw.get("priority"), PRIORITIES),
		"due": _iso(due),
		"overdue": is_overdue(due),
		"status_label": _text(raw.get("status_label")),
		"status_color": _choice(raw.get("status_color"), STATUS_COLORS),
	}


def is_desk_route(value: object) -> bool:
	return isinstance(value, str) and value.startswith(DESK_ROUTE_PREFIX)


def form_route(doctype: str, name: str) -> str:
	# Same path as frappe.utils.get_url_to_form, without the host.
	return f"{DESK_ROUTE_PREFIX}{quoted(slug(doctype))}/{quoted(name)}"


def is_overdue(due: date | datetime | None) -> bool:
	"""A date is overdue from the next day on, a datetime once it has passed."""
	if isinstance(due, datetime):
		return due < now_datetime()
	if isinstance(due, date):
		return due < getdate()
	return False


def parse_when(value: object) -> date | datetime | None:
	"""Read a date or datetime, or an ISO string of one; datetimes become naive in the system time zone."""
	if isinstance(value, str):
		try:
			value = date.fromisoformat(value)
		except ValueError:
			try:
				value = datetime.fromisoformat(value)
			except ValueError:
				return None
	if isinstance(value, datetime):
		if value.tzinfo:
			value = value.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
		return value
	return value if isinstance(value, date) else None


def _item_route(raw: dict) -> str | None:
	if is_desk_route(raw.get("route")):
		return raw["route"]
	doctype = _text(raw.get("reference_doctype"))
	name = _item_id(raw.get("reference_name"))
	return form_route(doctype, name) if doctype and name else None


def _item_id(value: object) -> str | None:
	if isinstance(value, int) and not isinstance(value, bool):
		return str(value)
	return _text(value)


def _plain_text(value: object) -> str | None:
	if not isinstance(value, str):
		return None
	return _text(" ".join(html.unescape(strip_html(value)).split()))


def _text(value: object) -> str | None:
	return (value.strip() or None) if isinstance(value, str) else None


def _full_name(user: object) -> str | None:
	user = _text(user)
	return get_fullname(user) if user else None


def _choice(value: object, choices: tuple[str, ...]) -> str:
	return value if isinstance(value, str) and value in choices else choices[0]


def _iso(value: date | datetime | None) -> str | None:
	if isinstance(value, datetime):
		return value.isoformat(timespec="seconds")
	return value.isoformat() if value else None


def _is_whole_number(value: object) -> bool:
	return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_text(value: object) -> bool:
	return isinstance(value, str) and bool(value.strip())


def _is_text_list(value: object) -> bool:
	return isinstance(value, list) and all(_is_text(item) for item in value)


def _is_json(value: object) -> bool:
	try:
		json.dumps(value)
	except (TypeError, ValueError):
		return False
	return True


def _is_dotted_path(value: object) -> bool:
	return isinstance(value, str) and bool(DOTTED_PATH_PATTERN.fullmatch(value))


def _is_optional(definition: dict, name: str, is_valid: Callable[[object], bool]) -> bool:
	return definition.get(name) is None or is_valid(definition[name])
