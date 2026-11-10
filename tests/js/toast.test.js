import assert from "node:assert/strict";
import test from "node:test";

import { newItemsText, toastToDrop } from "../../attention_center/public/js/attention_center/ui/toast.js";

// Frappe's __() with its placeholder substitution, without a translation.
globalThis.__ = (text, args = []) => text.replace(/\{(\d+)\}/g, (_, index) => args[index]);

const TEXT_CASES = [
	[1, "Assignments", "New item in Assignments"],
	[4, "Assignments", "4 new items in Assignments"],
	[3, null, "3 new items"],
];

for (const [count, label, expected] of TEXT_CASES) {
	test(`the toast for ${count} new items from ${label ?? "several sources"} reads "${expected}"`, () => {
		assert.equal(newItemsText(count, label), expected);
	});
}

// [name, the toasts shown oldest first, the one that makes room].
const DROP_CASES = [
	["the oldest when none is sticky", ["a", "b", "c"], [], "a"],
	["the oldest that is not sticky", ["a", "b", "c"], ["a"], "b"],
	["the oldest that is not sticky, past several sticky ones", ["a", "b", "c"], ["a", "b"], "c"],
	["the oldest when all are sticky", ["a", "b", "c"], ["a", "b", "c"], "a"],
];

for (const [name, ids, sticky, expected] of DROP_CASES) {
	test(`a new toast beyond three replaces ${name}`, () => {
		const toasts = ids.map((id) => ({ id, sticky: sticky.includes(id) }));

		assert.equal(toastToDrop(toasts).id, expected);
	});
}
