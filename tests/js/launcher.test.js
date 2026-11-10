import assert from "node:assert/strict";
import test from "node:test";

import { launcherLabel } from "../../attention_center/public/js/attention_center/ui/launcher.js";

// Frappe's __() with its placeholder substitution, without a translation.
globalThis.__ = (text, args = []) => text.replace(/\{(\d+)\}/g, (_, index) => args[index]);

const LABEL_CASES = [
	[{ count: "", unseen: false }, "Attention Center"],
	[{ count: "", unseen: true }, "Attention Center: new information is waiting"],
	[{ count: "1", unseen: false }, "Attention Center: 1 item needs your action"],
	[
		{ count: "1", unseen: true },
		"Attention Center: 1 item needs your action, and new information is waiting",
	],
	[{ count: "5", unseen: false }, "Attention Center: 5 items need your action"],
	[
		{ count: "99+", unseen: true },
		"Attention Center: 99+ items need your action, and new information is waiting",
	],
];

for (const [badge, expected] of LABEL_CASES) {
	test(`the launcher is named "${expected}"`, () => {
		assert.equal(launcherLabel(badge), expected);
	});
}
