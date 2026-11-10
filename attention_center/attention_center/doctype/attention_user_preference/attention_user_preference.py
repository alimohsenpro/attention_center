# Copyright (c) 2026, Attention Center Contributors and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr

VOLUME_PATTERN = re.compile(r"[0-9]{1,3}")


class AttentionUserPreference(Document):
	def validate(self) -> None:
		self.validate_volume()

	def validate_volume(self) -> None:
		# Empty means "use the default from the settings"; an Int column cannot be empty.
		volume = cstr(self.volume).strip()
		if not volume:
			self.volume = None
			return
		if not VOLUME_PATTERN.fullmatch(volume) or int(volume) > 100:
			frappe.throw(_("Volume must be empty, to use the default, or a whole number from 0 to 100."))
		self.volume = str(int(volume))
