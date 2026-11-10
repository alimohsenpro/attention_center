import assert from "node:assert/strict";
import test from "node:test";

import {
	retitle,
	watchTitle,
} from "../../attention_center/public/js/attention_center/util/title.js";

const RETITLE_CASES = [
	["adds the counter", ["ToDo", "", "5"], { title: "(5) ToDo", applied: "(5) " }],
	[
		"replaces its own counter",
		["(5) ToDo", "(5) ", "7"],
		{ title: "(7) ToDo", applied: "(7) " },
	],
	["shows the cap", ["(98) ToDo", "(98) ", "99+"], { title: "(99+) ToDo", applied: "(99+) " }],
	["removes its counter at zero", ["(7) ToDo", "(7) ", ""], { title: "ToDo", applied: "" }],
	["leaves a bare title bare at zero", ["ToDo", "", ""], { title: "ToDo", applied: "" }],
	[
		"counts a title the page rewrote",
		["Sales Invoice", "(7) ", "7"],
		{ title: "(7) Sales Invoice", applied: "(7) " },
	],
	[
		"keeps a page title that starts with brackets",
		["(2) Draft report", "", ""],
		{ title: "(2) Draft report", applied: "" },
	],
	[
		"prefixes such a title instead of eating it",
		["(2) Draft report", "", "4"],
		{ title: "(4) (2) Draft report", applied: "(4) " },
	],
];

for (const [name, [title, applied, count], expected] of RETITLE_CASES) {
	test(`retitle ${name}`, () => {
		assert.deepEqual(retitle(title, applied, count), expected);
	});
}

// A document whose <title> mutations reach the observer the way a browser delivers them.
function fakeDocument(title) {
	const element = {};
	const doc = {
		title,
		querySelector: (selector) => (selector === "title" ? element : null),
	};
	const watcher = { observed: null, disconnected: false };
	const observe = (callback) => {
		watcher.notify = callback;
		return {
			observe(target, options) {
				watcher.observed = { target, options };
			},
			disconnect() {
				watcher.disconnected = true;
			},
		};
	};
	return { doc, element, watcher, observe };
}

test("the counter comes back after the page rewrites the title", () => {
	const { doc, element, watcher, observe } = fakeDocument("Home");
	const title = watchTitle(doc, observe);
	assert.equal(watcher.observed.target, element);

	title.set("3");
	assert.equal(doc.title, "(3) Home");

	doc.title = "ToDo";
	watcher.notify();
	assert.equal(doc.title, "(3) ToDo");
});

test("the observer reacting to its own write changes nothing", () => {
	const { doc, watcher, observe } = fakeDocument("Home");
	const title = watchTitle(doc, observe);
	title.set("3");

	watcher.notify();
	watcher.notify();

	assert.equal(doc.title, "(3) Home");
});

test("the counter disappears when no action item is left", () => {
	const { doc, observe } = fakeDocument("Home");
	const title = watchTitle(doc, observe);
	title.set("12");

	title.set("");

	assert.equal(doc.title, "Home");
});

test("stopping removes the counter and stops watching", () => {
	const { doc, watcher, observe } = fakeDocument("Home");
	const title = watchTitle(doc, observe);
	title.set("99+");

	title.stop();

	assert.equal(doc.title, "Home");
	assert.equal(watcher.disconnected, true);
});
