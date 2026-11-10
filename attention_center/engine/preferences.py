"""The session user's own preferences: the settings' defaults, their overrides and their watermarks (§3.3).

Users have no desk permission on Attention User Preference: this module is the way to it, and every function
works on the row of the session user. None takes a user id, so none can reach another user's row [FR-PERM-01].
"""

import hashlib
import json
from datetime import datetime
from functools import cache

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime

from attention_center.engine.contract import parse_when

PREFERENCE = "Attention User Preference"
SETTINGS = "Attention Center Settings"
EDITABLE_FIELDS = (
	"sound_scope",
	"tone",
	"volume",
	"dnd_until",
	"auto_open_on_login",
	"display_mode",
	"launcher_collapsed",
)
STORED_FIELDS = (*EDITABLE_FIELDS, "watermarks", "last_auto_open_sid")
INHERIT = (None, "", "Default")
AUTO_OPEN = {"Yes": True, "No": False}
SOUNDS_URL = "/assets/attention_center/sounds/"


def get_stored() -> frappe._dict:
	"""The session user's stored preference; empty when they never changed one."""
	# Users cannot read the DocType; this is their own row (module docstring).
	stored = frappe.db.get_value(PREFERENCE, frappe.session.user, STORED_FIELDS, as_dict=True)
	return stored or frappe._dict()


def get_effective(stored: frappe._dict) -> dict:
	"""Every preference as it applies: the user's own value, else the default from the settings [FR-SET-02]."""
	settings = frappe.get_cached_doc(SETTINGS)
	dnd_until = stored.dnd_until
	return {
		"display_mode": _own_or(stored.display_mode, settings.default_display_mode),
		"auto_open_on_login": AUTO_OPEN.get(
			stored.auto_open_on_login, bool(settings.default_auto_open_on_login)
		),
		"sound_scope": _own_or(stored.sound_scope, settings.default_sound_scope),
		"tone": _own_or(stored.tone, settings.default_tone),
		"volume": cint(_own_or(stored.volume, settings.default_volume)),
		"dnd_until": dnd_until.isoformat(timespec="seconds")
		if dnd_until and dnd_until > now_datetime()
		else None,
		"launcher_collapsed": bool(stored.launcher_collapsed),
	}


def set_preferences(values: object) -> dict:
	"""Validate and store the session user's changes, then return their effective preferences.

	Only the preferences named in `values` change. An unknown name is rejected rather than ignored: the other
	stored values (watermarks, the auto-open session) are not the client's to write [FR-API-04].
	"""
	if not isinstance(values, dict):
		frappe.throw(_("Preferences must be an object of preference names and values."))
	unknown = sorted(str(name) for name in values if name not in EDITABLE_FIELDS)
	if unknown:
		frappe.throw(
			_("Unknown preferences: {0}. Allowed: {1}").format(", ".join(unknown), ", ".join(EDITABLE_FIELDS))
		)

	doc = _own_doc()
	doc.update({fieldname: _clean(fieldname, value) for fieldname, value in values.items()})
	_save(doc)
	return get_effective(get_stored())


def get_watermarks(stored: frappe._dict) -> dict[str, datetime]:
	"""When the user last viewed each source, naive in the system time zone like the sources' dates."""
	return {key: datetime.fromisoformat(seen) for key, seen in json.loads(stored.watermarks or "{}").items()}


def mark_seen(source_keys: list[str]) -> None:
	"""Set the watermark of each source to now, so that its `new_since` starts again from zero [FR-API-03]."""
	if not source_keys:
		return
	doc = _own_doc()
	seen = now_datetime().isoformat()
	doc.watermarks = {**json.loads(doc.watermarks or "{}"), **dict.fromkeys(source_keys, seen)}
	_save(doc)


def should_auto_open(stored: frappe._dict) -> bool:
	"""True until note_auto_opened is called in this login session [FR-ALERT-05]."""
	return stored.last_auto_open_sid != _session_hash()


def note_auto_opened() -> None:
	doc = _own_doc()
	doc.last_auto_open_sid = _session_hash()
	_save(doc)


def get_tones() -> list[dict]:
	"""The bundled tones with their role, translated label and URL (§7.5)."""
	return [
		{"id": tone["id"], "role": tone["role"], "label": _(tone["label"]), "url": SOUNDS_URL + tone["file"]}
		for tone in _tone_file()
	]


def _own_or(value: object, default: object) -> object:
	return default if value in INHERIT else value


@cache
def _tone_file() -> tuple[dict, ...]:
	with open(frappe.get_app_path("attention_center", "public", "sounds", "tones.json")) as file:
		return tuple(json.load(file))


def _clean(fieldname: str, value: object) -> object:
	"""The value to store, or a ValidationError naming the field."""
	label = _(frappe.get_meta(PREFERENCE).get_label(fieldname), context=PREFERENCE)
	if fieldname == "volume":
		# The controller accepts empty or a whole number from 0 to 100.
		return value
	if fieldname == "dnd_until":
		return _datetime(label, value)
	if fieldname == "launcher_collapsed":
		if not isinstance(value, int) or value not in (0, 1):
			frappe.throw(_("{0} must be true or false.").format(label))
		return int(value)

	choices = _choices(fieldname)
	if not isinstance(value, str) or value not in choices:
		frappe.throw(
			_("{0} must be one of: {1}").format(label, ", ".join(choice or '""' for choice in choices))
		)
	return value


def _choices(fieldname: str) -> list[str]:
	if fieldname == "tone":
		# Users pick one of the standard tones; the urgent, immediate and reminder tones are the organisation's.
		return ["", *(tone["id"] for tone in _tone_file() if tone["role"] == "standard")]
	return frappe.get_meta(PREFERENCE).get_options(fieldname).split("\n")


def _datetime(label: str, value: object) -> datetime | None:
	if value in (None, ""):
		return None
	when = parse_when(value) if isinstance(value, str) else None
	if not isinstance(when, datetime):
		frappe.throw(_("{0} must be a date and time in ISO format, or empty.").format(label))
	return when


def _own_doc() -> Document:
	"""The session user's preference, locked until the request ends so parallel writes do not overwrite each
	other; a new one when they have none yet (created on first write, §3.3)."""
	user = frappe.session.user
	if frappe.db.exists(PREFERENCE, user):
		return frappe.get_doc(PREFERENCE, user, for_update=True)
	return frappe.new_doc(PREFERENCE, user=user)


def _save(doc: Document) -> None:
	# Users cannot write the DocType; this module only ever saves the session user's own row.
	doc.save(ignore_permissions=True)


def _session_hash() -> str:
	# The session id is a credential: only its hash is stored, where System Managers can read it.
	return hashlib.sha256(frappe.session.sid.encode()).hexdigest()
