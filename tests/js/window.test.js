import assert from "node:assert/strict";
import test from "node:test";

import { newSinceText } from "../../attention_center/public/js/attention_center/ui/window.js";

// Frappe's __() with its placeholder substitution, without a translation.
globalThis.__ = (text, args = []) => text.replace(/\{(\d+)\}/g, (_, index) => args[index]);

const CASES = [
	[0, "Nothing new since you last looked"],
	[1, "1 new item since you last looked"],
	[5, "5 new items since you last looked"],
];

for (const [count, expected] of CASES) {
	test(`the login summary line for ${count} new action items reads "${expected}"`, () => {
		assert.equal(newSinceText(count), expected);
	});
}
