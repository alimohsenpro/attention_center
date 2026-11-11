import json
import os
import re

import frappe
from babel.messages.extract import extract_from_dir
from frappe.gettext.translate import PYTHON_KEYWORDS, get_catalog
from frappe.tests.utils import FrappeTestCase
from frappe.translate import get_translation_dict_from_file

from attention_center.sources.builtin import SOURCES

LANG = "ar"
APP = "attention_center"
# The extractors `bench generate-pot-file` runs on code. DocType and workspace strings have their own tests below.
CODE_EXTRACTORS = [
	("**.py", "frappe.gettext.extractors.python.extract"),
	("**.js", "frappe.gettext.extractors.javascript.extract"),
]
PLACEHOLDER = re.compile(r"\{\d+\}")
ARABIC_LETTER = re.compile("[\u0600-\u06ff]")


def doctype_strings(doctype: str) -> set[str]:
	strings = {doctype}
	for df in frappe.get_meta(doctype).fields:
		strings.update(filter(None, (df.label, df.description)))
		if df.fieldtype == "Select":
			strings.update(filter(None, (df.options or "").split("\n")))
	return strings


def read_app_translations() -> dict[str, str]:
	return get_translation_dict_from_file(frappe.get_app_path(APP, "translations", f"{LANG}.csv"), LANG, APP)


def code_messages() -> dict[tuple[str, str | None], str]:
	"""Every literal the app's code wraps in _() or __(), with its context, and where it first appears."""
	messages = {}
	for filename, lineno, message, _comments, context in extract_from_dir(
		frappe.get_app_path(APP), CODE_EXTRACTORS, keywords=PYTHON_KEYWORDS, directory_filter=is_source_dir
	):
		messages.setdefault((message, context), f"{filename}:{lineno}")
	return messages


def is_source_dir(path: str) -> bool:
	# public/dist holds the built bundles: the same strings again.
	name = os.path.basename(path)
	return not name.startswith((".", "_")) and name not in ("dist", "node_modules")


def data_messages() -> dict[tuple[str, str | None], str]:
	"""The texts the app translates from its own data rather than from a literal: the tone labels
	(engine/preferences.py) and the labels of the built-in sources, translated with the source DocType as context
	(api.py)."""
	with open(frappe.get_app_path(APP, "public", "sounds", "tones.json")) as file:
		messages = {(tone["label"], None): "tones.json" for tone in json.load(file)}
	messages.update({(source["label"], "Attention Source"): "sources/builtin.py" for source in SOURCES})
	return messages


def frappe_translations() -> dict[str, str]:
	"""Frappe's own Arabic for the texts it translates without a context."""
	return {
		message.id: message.string
		for message in get_catalog("frappe", LANG)
		if isinstance(message.string, str) and message.string and not message.context
	}


def translation_problem(
	message: str, context: str | None, translations: dict[str, str], frappe_arabic: dict[str, str]
) -> str | None:
	"""Why the text would not show in proper Arabic, or None. Frappe looks a text up with its context first, then
	without; a row without context also replaces Frappe's own Arabic for that text across the desk."""
	if context and f"{message}:{context}" in translations:
		arabic = translations[f"{message}:{context}"]
	elif message in translations:
		arabic = translations[message]
		if frappe_arabic.get(message, arabic) != arabic:
			return "Frappe translates this text differently: give it a context in the code and in the third column"
	else:
		return "no Arabic translation in ar.csv"
	if not ARABIC_LETTER.search(arabic):
		return "the translation has no Arabic text"
	if sorted(PLACEHOLDER.findall(arabic)) != sorted(PLACEHOLDER.findall(message)):
		return "the translation does not keep the placeholders of the text"
	return None


class TestArabicTranslations(FrappeTestCase):
	def test_workspace_strings_are_translated(self):
		# The desk translates the workspace name and its shortcut labels without a context.
		workspace = frappe.get_doc("Workspace", "Attention Center")
		translations = read_app_translations()

		for text in (workspace.name, *(shortcut.label for shortcut in workspace.shortcuts)):
			with self.subTest(text=text):
				self.assertIn(text, translations)

	def test_doctype_strings_are_translated_without_changing_frappe_wording(self):
		app_translations = read_app_translations()
		frappe_catalog = get_catalog("frappe", LANG)
		self.assertIsNotNone(frappe_catalog.get("Label"))

		doctypes = frappe.get_list("DocType", filters={"module": "Attention Center"}, pluck="name")
		self.assertIn("Attention Source", doctypes)
		for doctype in doctypes:
			for text in doctype_strings(doctype):
				if f"{text}:{doctype}" in app_translations:
					continue
				with self.subTest(doctype=doctype, text=text):
					self.assertTrue(text in app_translations, "no Arabic translation in ar.csv")
					self.assertIsNone(
						frappe_catalog.get(text),
						"Frappe translates this string too: put the DocType in the third column of ar.csv",
					)

	def test_every_text_of_the_code_has_arabic(self):
		messages = code_messages()
		# Without these the extraction found nothing to check, and the test would pass for that reason alone.
		self.assertIn(("What needs your attention", None), messages)
		self.assertIn(("Close", "Attention Center"), messages)
		self.assertIn(("This source is not available to you.", None), messages)
		messages.update(data_messages())
		translations = read_app_translations()
		frappe_arabic = frappe_translations()
		self.assertIn("Close", frappe_arabic)

		for (message, context), where in messages.items():
			with self.subTest(message=message, context=context, where=where):
				self.assertIsNone(translation_problem(message, context, translations, frappe_arabic))

	def test_a_text_without_proper_arabic_is_reported(self):
		translations = {
			"Saved": "تم الحفظ",
			"Open:Attention Center": "فتح",
			"Close": "إغلاق",
			"Reminder": "تذكير",
			"Page {0}": "الصفحة",
			"Draft": "Draft",
		}
		frappe_arabic = {"Close": "أغلق", "Reminder": "تذكير"}
		cases = (
			("Saved", None, None),
			("Open", "Attention Center", None),
			("Saved", "Attention Center", None),
			("Reminder", None, None),
			("Archived", None, "no Arabic translation"),
			("Open", None, "no Arabic translation"),
			("Close", "Attention Center", "Frappe translates this text differently"),
			("Page {0}", None, "placeholders"),
			("Draft", None, "no Arabic text"),
		)
		for message, context, expected in cases:
			with self.subTest(message=message, context=context):
				problem = translation_problem(message, context, translations, frappe_arabic)
				if expected is None:
					self.assertIsNone(problem)
				else:
					self.assertIn(expected, problem or "")
