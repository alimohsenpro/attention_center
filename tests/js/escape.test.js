import assert from "node:assert/strict";
import test from "node:test";

import { escapeHtml } from "../../attention_center/public/js/attention_center/util/escape.js";

const CASES = [
	["plain text", "Leave request", "Leave request"],
	["a script tag", "<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"],
	[
		"an image with a handler",
		'<img src=x onerror="alert(1)">',
		"&lt;img src=x onerror=&quot;alert(1)&quot;&gt;",
	],
	[
		"a quote that would end an attribute",
		"x' onmouseover='alert(1)",
		"x&#39; onmouseover=&#39;alert(1)",
	],
	["an ampersand", "Q&A", "Q&amp;A"],
	["text that is already escaped", "&lt;b&gt;", "&amp;lt;b&amp;gt;"],
	["Arabic text", "طلب إجازة <عاجل>", "طلب إجازة &lt;عاجل&gt;"],
	["a number", 42, "42"],
	["null", null, ""],
	["undefined", undefined, ""],
];

for (const [name, input, expected] of CASES) {
	test(`escapeHtml: ${name}`, () => {
		assert.equal(escapeHtml(input), expected);
	});
}
