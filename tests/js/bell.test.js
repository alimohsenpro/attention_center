import assert from "node:assert/strict";
import test from "node:test";

import {
	hideStandardBell,
	STANDARD_BELL_CSS,
} from "../../attention_center/public/js/attention_center/util/bell.js";

// A page head that holds elements, and elements that can leave it.
function fakeDocument() {
	const head = [];
	return {
		head: { children: head, append: (node) => head.push(node) },
		createElement: (tagName) => ({
			tagName,
			textContent: "",
			remove() {
				head.splice(head.indexOf(this), 1);
			},
		}),
	};
}

test("hiding the bell puts one rule for the stock navbar's bell in the page head", () => {
	const doc = fakeDocument();

	hideStandardBell(doc);

	assert.deepEqual(
		doc.head.children.map((node) => [node.tagName, node.textContent]),
		[["style", STANDARD_BELL_CSS]]
	);
	assert.match(
		STANDARD_BELL_CSS,
		/^\.navbar \.dropdown-notifications \{ display: none !important; \}$/
	);
});

test("undoing it takes the rule out of the page again", () => {
	const doc = fakeDocument();
	doc.head.append({ tagName: "link" });

	hideStandardBell(doc)();

	assert.deepEqual(
		doc.head.children.map((node) => node.tagName),
		["link"]
	);
});
