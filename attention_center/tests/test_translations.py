import frappe
from frappe.gettext.translate import get_catalog
from frappe.tests.utils import FrappeTestCase
from frappe.translate import get_translation_dict_from_file

LANG = "ar"


def doctype_strings(doctype: str) -> set[str]:
	strings = {doctype}
	for df in frappe.get_meta(doctype).fields:
		strings.update(filter(None, (df.label, df.description)))
		if df.fieldtype == "Select":
			strings.update(filter(None, (df.options or "").split("\n")))
	return strings


class TestArabicTranslations(FrappeTestCase):
	def test_doctype_strings_are_translated_without_changing_frappe_wording(self):
		app_translations = get_translation_dict_from_file(
			frappe.get_app_path("attention_center", "translations", f"{LANG}.csv"), LANG, "attention_center"
		)
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
