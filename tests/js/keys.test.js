import assert from "node:assert/strict";
import test from "node:test";

import {
	roveIndex,
	trapIndex,
} from "../../attention_center/public/js/attention_center/util/keys.js";

// [key, focused tab, right-to-left, tab to focus], in a list of four tabs.
const ROVING_CASES = [
	["ArrowRight", 0, false, 1],
	["ArrowRight", 3, false, 0],
	["ArrowLeft", 1, false, 0],
	["ArrowLeft", 0, false, 3],
	["ArrowLeft", 0, true, 1],
	["ArrowLeft", 3, true, 0],
	["ArrowRight", 1, true, 0],
	["ArrowRight", 0, true, 3],
	["Home", 2, false, 0],
	["Home", 2, true, 0],
	["End", 1, false, 3],
	["End", 1, true, 3],
	["ArrowDown", 1, false, -1],
	["Enter", 1, false, -1],
	["Tab", 1, true, -1],
];

for (const [key, index, rtl, expected] of ROVING_CASES) {
	test(`${key} on tab ${index} (${rtl ? "RTL" : "LTR"}) focuses ${expected}`, () => {
		assert.equal(roveIndex(key, index, 4, rtl), expected);
	});
}

test("in a list of one tab every arrow stays on it", () => {
	assert.equal(roveIndex("ArrowRight", 0, 1, false), 0);
	assert.equal(roveIndex("ArrowLeft", 0, 1, true), 0);
});

// [focused element, Shift held, element to focus or -1 for the browser], among three focusable elements.
const TRAP_CASES = [
	[2, false, 0],
	[0, true, 2],
	[0, false, -1],
	[1, false, -1],
	[1, true, -1],
	[2, true, -1],
	[-1, false, 0],
	[-1, true, 2],
];

for (const [index, backwards, expected] of TRAP_CASES) {
	test(`${
		backwards ? "Shift+Tab" : "Tab"
	} from element ${index} of 3 goes to ${expected}`, () => {
		assert.equal(trapIndex(index, 3, backwards), expected);
	});
}

test("with a single focusable element Tab and Shift+Tab keep focus on it", () => {
	assert.equal(trapIndex(0, 1, false), 0);
	assert.equal(trapIndex(0, 1, true), 0);
});
