"""Declarative sources: one permission-aware query on one DocType, run as the session user (§4.4)."""

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, time

import frappe
from frappe import _
from frappe.database.database import get_query_execution_timeout
from frappe.utils import cstr, today

from attention_center.engine.contract import (
	COUNT_CAP,
	PRIORITIES,
	TIME_BUDGET_SECONDS,
	is_overdue,
	parse_when,
)

# The count and the priority order cover the newest WINDOW rows (see DocTypeQuery.items).
WINDOW = COUNT_CAP + 1
PLACEHOLDER_PATTERN = re.compile(r"\{(user|today)\}")
URGENCY_ORDER = ("immediate", "urgent", "normal")


def get_count(source: frappe._dict, user: str, since: datetime | None = None) -> dict:
	"""Counters in the shape of a python source's get_count; contract.normalize_count caps them."""
	return DocTypeQuery(source, user).count(since)


def get_items(source: frappe._dict, user: str, start: int, page_length: int) -> list[dict]:
	"""Raw items in the shape of a python source's get_items; contract.normalize_items cleans them."""
	return DocTypeQuery(source, user).items(start, page_length)


def resolve_filters(filters: list, user: str) -> list:
	"""Replace {user} and {today} inside filter values.

	Only values change: frappe.get_list escapes them like any filter value, so no SQL is built here.
	"""
	values = {"user": user, "today": today()}

	def resolve(value: object) -> object:
		if isinstance(value, str):
			return PLACEHOLDER_PATTERN.sub(lambda match: values[match.group(1)], value)
		if isinstance(value, list):
			return [resolve(item) for item in value]
		return value

	return [[field, operator, resolve(value)] for field, operator, value in filters]


@contextmanager
def statement_timeout(seconds: float) -> Iterator[None]:
	"""Abort a statement that runs longer than `seconds`, then restore the timeout Frappe set on connecting."""
	frappe.db.set_execution_timeout(seconds)
	try:
		yield
	finally:
		frappe.db.set_execution_timeout(get_query_execution_timeout())


class DocTypeQuery:
	"""A declarative source run for `user`, who must be the session user.

	frappe.get_list applies the role permissions, User Permissions and permission_query_conditions of that
	user [FR-PERM-02] and leaves out fields above their permission level, so a mapped field may be missing.
	"""

	def __init__(self, source: frappe._dict, user: str):
		self.source = source
		self.user = user
		self.table = f"`tab{source.reference_doctype}`"
		self.filters = resolve_filters(json.loads(source.filters_json or "[]"), user)
		self.priority_map = json.loads(source.priority_map_json or "{}")

	def count(self, since: datetime | None) -> dict:
		"""Count the newest WINDOW rows; an urgent or overdue row older than those is not counted.

		Every row is new to a user who has no watermark (`since`) for the source yet.
		"""
		source = self.source
		rows = self.rows(source.date_field, source.priority_field, source.due_field, start=0, limit=WINDOW)
		dates = [moment for row in rows if (moment := _moment(row.get(source.date_field)))]
		priorities = [self.priority(row) for row in rows]
		return {
			"count": len(rows),
			"urgent": priorities.count("urgent"),
			"immediate": priorities.count("immediate"),
			"overdue": sum(self.is_overdue(row) for row in rows),
			"latest": max(dates, default=None),
			"new_since": len(rows) if since is None else sum(moment > since for moment in dates),
		}

	def items(self, start: int, page_length: int) -> list[dict]:
		"""One page of items: overdue first, then immediate, urgent, normal, then newest [FR-API-02].

		The order needs the mapped priority, so it is applied in Python to the newest WINDOW rows, which the
		query returns newest first. Rows past the window, when more than COUNT_CAP are pending, follow in
		date order only.
		"""
		source = self.source
		fields = (
			source.title_field,
			source.from_field,
			source.date_field,
			source.priority_field,
			source.due_field,
			source.status_field,
			source.route_field,
			source.route_doctype_field,
			source.route_name_field,
		)
		window = self.rows(*fields, start=0, limit=WINDOW)
		end = start + page_length
		page = sorted(window, key=self.urgency)[start:end]
		if len(window) == WINDOW and end > WINDOW:
			tail_start = max(start, WINDOW)
			page += self.rows(*fields, start=tail_start, limit=end - tail_start)
		return [self.item(row) for row in page]

	def rows(self, *fieldnames: str | None, start: int, limit: int) -> list[frappe._dict]:
		columns = dict.fromkeys(fieldname for fieldname in ("name", *fieldnames) if fieldname)
		with statement_timeout(TIME_BUDGET_SECONDS):
			return frappe.get_list(
				self.source.reference_doctype,
				filters=self.filters,
				fields=[f"{self.table}.`{column}`" for column in columns],
				# The name breaks ties so that the window and the rows after it never overlap.
				order_by=f"{self.table}.`{self.source.date_field}` desc, {self.table}.`name` desc",
				limit_start=start,
				limit_page_length=limit,
				user=self.user,
			)

	def priority(self, row: frappe._dict) -> str:
		"""The mapped priority; without a map the field must hold a priority itself."""
		value = row.get(self.source.priority_field)
		priority = self.priority_map.get(cstr(value), value)
		return priority if priority in PRIORITIES else "normal"

	def is_overdue(self, row: frappe._dict) -> bool:
		return is_overdue(parse_when(row.get(self.source.due_field)))

	def urgency(self, row: frappe._dict) -> tuple[bool, int]:
		return not self.is_overdue(row), URGENCY_ORDER.index(self.priority(row))

	def item(self, row: frappe._dict) -> dict:
		source = self.source
		status = row.get(source.status_field)
		reference_doctype, reference_name = self.reference(row)
		return {
			"id": row.name,
			"title": row.get(source.title_field),
			# contract.normalize_item opens the reference instead when this is not a desk route.
			"route": row.get(source.route_field),
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			# A value that is not a user id is shown as it is (frappe.utils.get_fullname).
			"from_user": row.get(source.from_field),
			"date": row.get(source.date_field),
			"priority": self.priority(row),
			"due": row.get(source.due_field),
			"status_label": _(status) if isinstance(status, str) and status else None,
		}

	def reference(self, row: frappe._dict) -> tuple[str, str]:
		"""The document the route fields point to, or the row itself when they do not name one."""
		doctype = row.get(self.source.route_doctype_field)
		name = row.get(self.source.route_name_field)
		if doctype and name:
			return doctype, name
		return self.source.reference_doctype, row.name


def _moment(value: object) -> datetime | None:
	"""A date or datetime as a datetime, so that a date field compares with the watermark."""
	when = parse_when(value)
	if when is None or isinstance(when, datetime):
		return when
	return datetime.combine(when, time.min)
