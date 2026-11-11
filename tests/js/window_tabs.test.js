import assert from "node:assert/strict";
import test from "node:test";

import { ANNOUNCEMENTS } from "../../attention_center/public/js/attention_center/util/announcements.js";
import {
	ALL_TAB,
	buildTabs,
	itemFetcher,
} from "../../attention_center/public/js/attention_center/util/window_tabs.js";

// Frappe's __() with its placeholder substitution, without a translation.
globalThis.__ = (text, args = []) => text.replace(/\{(\d+)\}/g, (_, index) => args[index]);

const source = (key, kind, fields = {}) => ({
	key,
	label: key.split(".")[1],
	kind,
	state: "ok",
	count: 0,
	capped: false,
	urgent: 0,
	immediate: 0,
	overdue: 0,
	new_since: 0,
	list_route: null,
	...fields,
});

const summary = (sources, totals = {}) => ({
	sources,
	totals: { action: 0, attention: 0, info_new: 0, ...totals },
});

test("All comes first, then the action sources, then the info sources, each in summary order", () => {
	const tabs = buildTabs(
		summary([
			source("app.notifications", "info"),
			source("app.approvals", "action"),
			source("app.news", "info"),
			source("app.tasks", "action"),
		])
	);

	assert.deepEqual(
		tabs.map((tab) => tab.id),
		[ALL_TAB, "app.approvals", "app.tasks", "app.notifications", "app.news"]
	);
	assert.equal(tabs[0].label, "All");
	assert.deepEqual(tabs[0].sources, ["app.approvals", "app.tasks"]);
	assert.deepEqual(tabs[3].sources, ["app.notifications"]);
	assert.equal(tabs[3].label, "notifications");
});

test("before the first summary there is only the All tab, showing no source", () => {
	assert.deepEqual(buildTabs(null), [
		{
			id: ALL_TAB,
			label: "All",
			sources: [],
			marks: [],
			counter: "",
			attention: false,
			unseen: false,
			listRoute: null,
		},
	]);
});

test("the All counter is the launcher's action count, capped like it", () => {
	const tabs = buildTabs(
		summary(
			[
				source("app.a", "action", { count: 99, capped: true }),
				source("app.b", "action", { count: 3 }),
			],
			{ action: 102, attention: 1 }
		)
	);

	assert.equal(tabs[0].counter, "99+");
	assert.equal(tabs[0].attention, true);
	assert.equal(tabs[1].counter, "99+");
	assert.equal(tabs[2].counter, "3");
});

const SOURCE_TAB_CASES = [
	["no items", source("app.a", "action"), { counter: "", attention: false, unseen: false }],
	[
		"normal items",
		source("app.a", "action", { count: 4 }),
		{ counter: "4", attention: false, unseen: false },
	],
	[
		"an urgent item",
		source("app.a", "action", { count: 4, urgent: 1 }),
		{ counter: "4", attention: true, unseen: false },
	],
	[
		"an immediate item",
		source("app.a", "action", { count: 1, immediate: 1 }),
		{ counter: "1", attention: true, unseen: false },
	],
	[
		"an overdue item",
		source("app.a", "action", { count: 2, overdue: 1 }),
		{ counter: "2", attention: true, unseen: false },
	],
	[
		"new items of an action source",
		source("app.a", "action", { count: 2, new_since: 2 }),
		{ counter: "2", attention: false, unseen: false },
	],
	[
		"new information",
		source("app.n", "info", { count: 5, new_since: 2 }),
		{ counter: "5", attention: false, unseen: true },
	],
	[
		"information already seen",
		source("app.n", "info", { count: 5 }),
		{ counter: "5", attention: false, unseen: false },
	],
	[
		"urgent counters of an info source",
		source("app.n", "info", { count: 1, urgent: 1 }),
		{ counter: "1", attention: false, unseen: false },
	],
	[
		"a failed source",
		source("app.a", "action", { state: "error", count: 0, urgent: 0 }),
		{ counter: "", attention: false, unseen: false },
	],
];

for (const [name, input, expected] of SOURCE_TAB_CASES) {
	test(`a source tab with ${name}`, () => {
		const tab = buildTabs(summary([input])).find((candidate) => candidate.id === input.key);
		assert.deepEqual(
			{ counter: tab.counter, attention: tab.attention, unseen: tab.unseen },
			expected
		);
	});
}

test("a source tab links to the source's own page only through a desk route", () => {
	const tabs = buildTabs(
		summary([
			source("app.a", "action", { list_route: "/app/todo?status=Open" }),
			source("app.b", "action", { list_route: "https://example.com/app/todo" }),
			source("app.c", "action"),
		])
	);

	assert.deepEqual(
		tabs.map((tab) => tab.listRoute),
		[null, "/app/todo?status=Open", null, null]
	);
});

test("Announcements comes last, after the info sources, and All shows it among the action sources", () => {
	const tabs = buildTabs(
		summary([
			source(ANNOUNCEMENTS, "action"),
			source("app.notifications", "info"),
			source("app.approvals", "action"),
		])
	);

	assert.deepEqual(
		tabs.map((tab) => tab.id),
		[ALL_TAB, "app.approvals", "app.notifications", ANNOUNCEMENTS]
	);
	assert.deepEqual(tabs[0].sources, [ANNOUNCEMENTS, "app.approvals"]);
});

test("viewing All marks every action source seen but the announcements, which the Announcements tab marks", () => {
	const tabs = buildTabs(
		summary([
			source("app.approvals", "action"),
			source(ANNOUNCEMENTS, "action"),
			source("app.tasks", "action"),
			source("app.notifications", "info"),
		])
	);

	assert.deepEqual(
		tabs.map((tab) => [tab.id, tab.marks]),
		[
			[ALL_TAB, ["app.approvals", "app.tasks"]],
			["app.approvals", ["app.approvals"]],
			["app.tasks", ["app.tasks"]],
			["app.notifications", ["app.notifications"]],
			[ANNOUNCEMENTS, [ANNOUNCEMENTS]],
		]
	);
});

const ANNOUNCEMENT_TAB_CASES = [
	["nothing", {}, { counter: "", attention: false, unseen: false }],
	[
		"a new announcement for information",
		{ new_since: 1 },
		{ counter: "", attention: false, unseen: true },
	],
	[
		"one awaiting acknowledgement, seen",
		{ count: 1 },
		{ counter: "1", attention: false, unseen: false },
	],
	[
		"a new immediate one awaiting acknowledgement",
		{ count: 2, immediate: 1, new_since: 1 },
		{ counter: "2", attention: true, unseen: true },
	],
	[
		"a failed source",
		{ state: "error", count: 1, new_since: 1 },
		{ counter: "", attention: false, unseen: false },
	],
];

for (const [name, counts, expected] of ANNOUNCEMENT_TAB_CASES) {
	test(`the Announcements tab with ${name}`, () => {
		const tab = buildTabs(summary([source(ANNOUNCEMENTS, "action", counts)])).at(-1);
		assert.deepEqual(
			{ counter: tab.counter, attention: tab.attention, unseen: tab.unseen },
			expected
		);
	});
}

test("All takes only the announcements awaiting acknowledgement; every other tab gets a source's items", async () => {
	const calls = [];
	const api = {
		getItems: async (key, start, size) => calls.push(["getItems", key, start, size]),
		getAnnouncementsToAcknowledge: async (start, size) =>
			calls.push(["getAnnouncementsToAcknowledge", start, size]),
	};
	const [all, approvals, announcements] = buildTabs(
		summary([source("app.approvals", "action"), source(ANNOUNCEMENTS, "action")])
	);

	await itemFetcher(all, api)("app.approvals", 0, 10);
	await itemFetcher(all, api)(ANNOUNCEMENTS, 10, 10);
	await itemFetcher(approvals, api)("app.approvals", 0, 10);
	await itemFetcher(announcements, api)(ANNOUNCEMENTS, 0, 10);

	assert.deepEqual(calls, [
		["getItems", "app.approvals", 0, 10],
		["getAnnouncementsToAcknowledge", 10, 10],
		["getItems", "app.approvals", 0, 10],
		["getItems", ANNOUNCEMENTS, 0, 10],
	]);
});
