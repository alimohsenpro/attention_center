# Copyright (c) 2026, Attention Center Contributors and contributors
# For license information, please see license.txt

import json
import re

import frappe
from frappe import _
from frappe.model import no_value_fields, numeric_fieldtypes
from frappe.model.document import Document
from frappe.model.meta import Meta
from frappe.utils import cint, cstr, escape_html, flt

from attention_center.engine.contract import KEY_PATTERN, PRIORITIES
from attention_center.engine.registry import clear_visibility_cache

FILTER_OPERATORS = ("=", "!=", ">", "<", ">=", "<=", "in", "not in", "like", "is")
LIST_OPERATORS = ("in", "not in")
IS_VALUES = ("set", "not set")
PLACEHOLDER_PATTERN = re.compile(r"\{[^{}]*\}")
PLACEHOLDERS = ("{user}", "{today}")
MAPPED_FIELDS = ("title_field", "from_field", "date_field", "priority_field", "due_field", "status_field")
REQUIRED_MAPPED_FIELDS = ("title_field", "date_field")
ROUTE_FIELDS = ("route_field", "route_doctype_field", "route_name_field")
CALLABLE_FIELDS = ("get_count", "get_items", "get_recipients", "watch_doctypes")
REQUIRED_CALLABLE_FIELDS = ("get_count", "get_items")
ADMIN_FIELDS = frozenset(("enabled", "sort_order", "label", "roles", "user_groups"))


class AttentionSource(Document):
	def validate(self) -> None:
		self.validate_origin()
		self.validate_key()
		self.validate_list_route()
		if self.source_type == "Python":
			self.validate_python_source()
		else:
			self.validate_query_source()

	def on_update(self) -> None:
		clear_visibility_cache()

	def after_delete(self) -> None:
		clear_visibility_cache()

	def validate_origin(self) -> None:
		# `from_hooks` is set only by the hook sync in server code; a client cannot send document flags.
		if self.flags.from_hooks:
			return

		before = self.get_doc_before_save()
		if cint(self.is_system) != cint(before.is_system if before else 0):
			frappe.throw(_("Only an app's hooks can declare a system source."))
		if not self.is_system and self.app:
			frappe.throw(_("Only an app's hooks can set {0}.").format(self.field_label("app")))

		if before and self.is_system:
			changed = self.changed_definition_fields(before)
			if changed:
				frappe.throw(
					_(
						"This source is declared by an app's hooks. Only Enabled, Sort Order, Label and the targeting can be changed. Changed: {0}"
					).format(", ".join(changed))
				)

	def changed_definition_fields(self, before: Document) -> list[str]:
		return [
			_(df.label, context=self.doctype)
			for df in self.meta.fields
			if df.fieldtype not in no_value_fields
			and df.fieldname not in ADMIN_FIELDS
			and _comparable(df.fieldtype, self.get(df.fieldname))
			!= _comparable(df.fieldtype, before.get(df.fieldname))
		]

	def validate_key(self) -> None:
		if not KEY_PATTERN.fullmatch(self.key or ""):
			frappe.throw(
				_(
					"The key must look like app.identifier: lowercase letters, digits and underscores, in at least two parts separated by dots."
				)
			)

	def validate_list_route(self) -> None:
		if self.list_route and not self.list_route.startswith("/app/"):
			frappe.throw(_("{0} must start with /app/.").format(self.field_label("list_route")))

	def validate_python_source(self) -> None:
		if not self.is_system:
			frappe.throw(_("Python sources can only be declared in an app's hooks."))

		missing = [
			self.field_label(fieldname) for fieldname in REQUIRED_CALLABLE_FIELDS if not self.get(fieldname)
		]
		if missing:
			frappe.throw(_("A Python source needs {0}.").format(", ".join(missing)))

	def validate_query_source(self) -> None:
		if any(self.get(fieldname) for fieldname in CALLABLE_FIELDS):
			frappe.throw(_("Only Python sources declared in an app's hooks can name callables."))

		meta = self.reference_meta()
		columns = frozenset(meta.get_valid_columns())
		self.validate_mapped_fields(columns)
		self.validate_recipient_fields(columns)
		self.validate_filters(columns)
		self.validate_priority_map()

	def reference_meta(self) -> Meta:
		if not self.reference_doctype:
			frappe.throw(
				_("{0} is required for a DocType Query source.").format(self.field_label("reference_doctype"))
			)
		if not frappe.db.exists("DocType", self.reference_doctype):
			frappe.throw(
				_("Reference DocType {0} does not exist.").format(escape_html(self.reference_doctype))
			)

		meta = frappe.get_meta(self.reference_doctype)
		if meta.istable or meta.issingle:
			frappe.throw(
				_(
					"{0} is a child table or a Single DocType. Choose a DocType that has its own records."
				).format(_(self.reference_doctype))
			)
		return meta

	def validate_mapped_fields(self, columns: frozenset[str]) -> None:
		for fieldname in REQUIRED_MAPPED_FIELDS:
			if not self.get(fieldname):
				frappe.throw(
					_("{0} is required for a DocType Query source.").format(self.field_label(fieldname))
				)

		for fieldname in MAPPED_FIELDS + ROUTE_FIELDS:
			mapped = self.get(fieldname)
			if mapped and mapped not in columns:
				self.throw_unknown_field(self.field_label(fieldname), mapped)

		if bool(self.route_doctype_field) != bool(self.route_name_field):
			frappe.throw(
				_("Set {0} and {1} together.").format(
					self.field_label("route_doctype_field"), self.field_label("route_name_field")
				)
			)

	def validate_recipient_fields(self, columns: frozenset[str]) -> None:
		for fieldname in cstr(self.recipient_fields).split(","):
			fieldname = fieldname.strip()
			if fieldname and fieldname not in columns:
				self.throw_unknown_field(self.field_label("recipient_fields"), fieldname)

	def validate_filters(self, columns: frozenset[str]) -> None:
		filters = self.parse_json("filters_json")
		if filters is None:
			return

		shape_message = _("{0} must be a list of [field, operator, value] conditions.").format(
			self.field_label("filters_json")
		)
		if not isinstance(filters, list):
			frappe.throw(shape_message)

		for condition in filters:
			if not (isinstance(condition, list) and len(condition) == 3):
				frappe.throw(shape_message)
			field, operator, value = condition
			if not isinstance(field, str) or field not in columns:
				self.throw_unknown_field(self.field_label("filters_json"), cstr(field))
			if operator not in FILTER_OPERATORS:
				frappe.throw(
					_("Filter on {0} uses the operator {1}. Allowed operators: {2}").format(
						field, escape_html(cstr(operator)), ", ".join(FILTER_OPERATORS)
					)
				)
			validate_filter_value(field, operator, value)

	def validate_priority_map(self) -> None:
		mapping = self.parse_json("priority_map_json")
		if mapping is None:
			return

		if not isinstance(mapping, dict) or any(value not in PRIORITIES for value in mapping.values()):
			frappe.throw(
				_("{0} must map values of the priority field to {1}.").format(
					self.field_label("priority_map_json"), ", ".join(PRIORITIES)
				)
			)
		if not self.priority_field:
			frappe.throw(
				_("Set {0} to use {1}.").format(
					self.field_label("priority_field"), self.field_label("priority_map_json")
				)
			)

	def parse_json(self, fieldname: str) -> object:
		text = cstr(self.get(fieldname)).strip()
		if not text:
			return None
		try:
			return json.loads(text)
		except ValueError:
			frappe.throw(_("{0} is not valid JSON.").format(self.field_label(fieldname)))

	def field_label(self, fieldname: str) -> str:
		return _(self.meta.get_label(fieldname), context=self.doctype)

	def throw_unknown_field(self, label: str, fieldname: str) -> None:
		frappe.throw(
			_("{0}: {1} has no field {2}.").format(
				label, _(self.reference_doctype), frappe.bold(escape_html(fieldname))
			)
		)


def validate_filter_value(field: str, operator: str, value: object) -> None:
	if operator in LIST_OPERATORS and not isinstance(value, list):
		frappe.throw(_("Filter on {0}: {1} takes a list of values.").format(field, operator))
	values = value if operator in LIST_OPERATORS else [value]
	if any(isinstance(item, list | dict) for item in values):
		frappe.throw(
			_("Filter on {0}: a value must be text or a number. Only in and not in take a list.").format(
				field
			)
		)
	if operator == "is" and value not in IS_VALUES:
		frappe.throw(_('Filter on {0}: the "is" operator takes "set" or "not set".').format(field))

	for item in values:
		if not isinstance(item, str):
			continue
		unknown = sorted(set(PLACEHOLDER_PATTERN.findall(item)) - set(PLACEHOLDERS))
		if unknown:
			frappe.throw(
				_("Filter on {0} uses an unknown placeholder {1}. Supported placeholders: {2}").format(
					field, escape_html(", ".join(unknown)), ", ".join(PLACEHOLDERS)
				)
			)


def _comparable(fieldtype: str, value: object) -> object:
	# The desk sends "" or None for empty values and the database returns typed numbers.
	return flt(value) if fieldtype in numeric_fieldtypes else cstr(value)
