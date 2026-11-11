import assert from "node:assert/strict";
import test from "node:test";

import {
	newItemsText,
	toastToDrop,
} from "../../attention_center/public/js/attention_center/ui/toast.js";

// Frappe's __() with its placeholder substitution, without a translation.
globalThis.__ = (text, args = []) => text.replace(/\{(\d+)\}/g, (_, index) => args[index]);

const TEXT_CASES = [
	[1, "Assignments", "New item in Assignments"],
	[4, "Assignments", "4 new items in Assignments"],
	[3, null, "3 new items"],
];

for (const [count, label, expected] of TEXT_CASES) {
	test(`the toast for ${count} new items from ${
		label ?? "several sources"
	} reads "${expected}"`, () => {
		assert.equal(newItemsText(count, label), expected);
	});
}

// [name, the toasts shown oldest first, those of them that are sticky, whether the newcomer is sticky, the one
// that makes room or null when the newcomer is not shown].
const DROP_CASES = [
	["a new toast replaces the oldest when none is sticky", ["a", "b", "c"], [], false, "a"],
	["a new toast replaces the oldest that is not sticky", ["a", "b", "c"], ["a"], false, "b"],
	[
		"a new toast replaces the oldest that is not sticky, past several sticky ones",
		["a", "b", "c"],
		["a", "b"],
		false,
		"c",
	],
	[
		"a new sticky toast replaces the oldest that is not sticky",
		["a", "b", "c"],
		["a", "b"],
		true,
		"c",
	],
	[
		"a new sticky toast replaces the oldest when all are sticky",
		["a", "b", "c"],
		["a", "b", "c"],
		true,
		"a",
	],
	[
		"a new toast that is not sticky replaces none when all are sticky",
		["a", "b", "c"],
		["a", "b", "c"],
		false,
		null,
	],
];

for (const [name, ids, sticky, newcomerSticky, expected] of DROP_CASES) {
	test(`beyond three toasts, ${name}`, () => {
		const toasts = ids.map((id) => ({ id, sticky: sticky.includes(id) }));

		assert.equal(toastToDrop(toasts, newcomerSticky)?.id ?? null, expected);
	});
}
