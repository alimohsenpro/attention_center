import assert from "node:assert/strict";
import test from "node:test";

import {
	ANNOUNCEMENTS,
	arrivedPriority,
	toastUnseenImmediate,
	withAnnouncementPriority,
} from "../../attention_center/public/js/attention_center/util/announcements.js";

const NOW = "2026-11-10 10:00:00";
const PREFS = { sound_scope: "Action Items", dnd_until: null };
const BEFORE = "2026-11-10T09:00:00";

const item = (priority, date) => ({ id: `${priority}-${date}`, priority, date });

// [name, items, since, expected]
const ARRIVAL_CASES = [
	["nothing arrived", [item("immediate", "2026-11-10T08:00:00")], BEFORE, null],
	["one normal arrived", [item("normal", "2026-11-10T09:30:00")], BEFORE, "normal"],
	[
		"an immediate one arrived beside a normal one",
		[item("normal", "2026-11-10T09:30:00"), item("immediate", "2026-11-10T09:45:00")],
		BEFORE,
		"immediate",
	],
	[
		"an urgent one arrived; the immediate one is older",
		[item("immediate", "2026-11-10T08:00:00"), item("urgent", "2026-11-10T09:30:00")],
		BEFORE,
		"urgent",
	],
	["one arrived at the very time of the latest one", [item("urgent", BEFORE)], BEFORE, null],
	[
		"the previous summary held none, so every one arrived",
		[item("urgent", "2026-11-10T08:00:00")],
		null,
		"urgent",
	],
];

for (const [name, items, since, expected] of ARRIVAL_CASES) {
	test(`the priority of the announcements that arrived when ${name}: ${expected}`, () => {
		assert.equal(arrivedPriority(items, since), expected);
	});
}

const announcementsSource = (latest) => ({ key: ANNOUNCEMENTS, latest });
const previous = { sources: [announcementsSource(BEFORE)] };
const normalAlert = {
	source: ANNOUNCEMENTS,
	level: "normal",
	count: 1,
	toast: true,
	sticky: false,
	sound: "standard",
};
const otherAlert = { ...normalAlert, source: "app.tasks" };

// A server method that records its calls and gives the same answer to each.
function fetcher(answer) {
	const calls = [];
	const fetchItems = async (...args) => {
		calls.push(args);
		if (answer instanceof Error) throw answer;
		return answer;
	};
	return { calls, fetchItems };
}

test("a new immediate announcement for information raises the sticky toast and the immediate tone", async () => {
	const { calls, fetchItems } = fetcher({
		state: "ok",
		items: [item("immediate", "2026-11-10T09:50:00")],
	});

	const alerts = await withAnnouncementPriority(
		[otherAlert, normalAlert],
		previous,
		fetchItems,
		{
			prefs: PREFS,
			now: NOW,
		}
	);

	assert.deepEqual(alerts, [
		otherAlert,
		{ ...normalAlert, level: "immediate", sticky: true, sound: "immediate" },
	]);
	assert.deepEqual(calls, [[ANNOUNCEMENTS, 0, 50]]);
});

test("a new normal announcement keeps its alert", async () => {
	const { fetchItems } = fetcher({
		state: "ok",
		items: [item("normal", "2026-11-10T09:50:00")],
	});

	const alerts = await withAnnouncementPriority([normalAlert], previous, fetchItems, {
		prefs: PREFS,
		now: NOW,
	});

	assert.deepEqual(alerts, [normalAlert]);
});

// [name, alerts, answer of the server, whether the server is asked]
const UNCHANGED_CASES = [
	[
		"no announcement alert",
		[otherAlert],
		{ state: "ok", items: [item("immediate", NOW)] },
		false,
	],
	[
		"an alert that is immediate already",
		[{ ...normalAlert, level: "immediate", sticky: true, sound: "immediate" }],
		{ state: "ok", items: [item("immediate", NOW)] },
		false,
	],
	["a failed request", [normalAlert], new Error("offline"), true],
	["a source in error", [normalAlert], { state: "error", items: [] }, true],
];

for (const [name, given, answer, asks] of UNCHANGED_CASES) {
	test(`the alerts stay as the counters tell with ${name}`, async () => {
		const { calls, fetchItems } = fetcher(answer);

		const alerts = await withAnnouncementPriority(given, previous, fetchItems, {
			prefs: PREFS,
			now: NOW,
		});

		assert.deepEqual(alerts, given);
		assert.equal(calls.length, asks ? 1 : 0);
	});
}

// A summary holding the announcements source with these counts, beside another source.
function loadedSummary(counts) {
	return {
		sources: [
			{ key: "app.tasks", state: "ok", new_since: 2 },
			{ key: ANNOUNCEMENTS, state: "ok", new_since: 0, ...counts },
		],
	};
}

// The server leaves out of both `new_since` and its answer the announcements the user acknowledged or wrote
// (test_announcements.py, TestUnseen).
// [name, previous summary, announcements counts, answer of get_unseen_announcements, count the toast shows (null for
// none), whether the server is asked]
const PAGE_LOAD_CASES = [
	[
		"an immediate announcement not seen yet",
		null,
		{ new_since: 1 },
		{ count: 1, immediate: 1 },
		1,
		true,
	],
	[
		"an immediate announcement among several not seen yet",
		null,
		{ new_since: 2 },
		{ count: 2, immediate: 1 },
		2,
		true,
	],
	[
		"only a normal announcement not seen yet",
		null,
		{ new_since: 1 },
		{ count: 1, immediate: 0 },
		null,
		true,
	],
	[
		"fewer announcements not seen than the summary counted, one acknowledged since in another tab",
		null,
		{ new_since: 2 },
		{ count: 1, immediate: 1 },
		1,
		true,
	],
	[
		"none not seen any more, the immediate one acknowledged since in another tab",
		null,
		{ new_since: 1 },
		{ count: 0, immediate: 0 },
		null,
		true,
	],
	["every announcement seen", null, { new_since: 0 }, { count: 0, immediate: 0 }, null, false],
	[
		"the source in error",
		null,
		{ state: "error", new_since: 0 },
		{ count: 1, immediate: 1 },
		null,
		false,
	],
	["a failed request", null, { new_since: 1 }, new Error("offline"), null, true],
	[
		"a later summary of the page load",
		loadedSummary({ new_since: 0 }),
		{ new_since: 1 },
		{ count: 1, immediate: 1 },
		null,
		false,
	],
];

for (const [name, previousSummary, counts, answer, shown, asks] of PAGE_LOAD_CASES) {
	test(`at page load, the announcement toast with ${name}: ${shown ?? "none"}`, async () => {
		const { calls, fetchItems: fetchUnseen } = fetcher(answer);
		const toasts = [];
		const listener = toastUnseenImmediate({
			fetchUnseen,
			show: (count) => toasts.push(count),
		});

		await listener({ previous: previousSummary, summary: loadedSummary(counts) });

		assert.deepEqual(toasts, shown === null ? [] : [shown]);
		assert.equal(calls.length, asks ? 1 : 0);
	});
}

test("when the page loads, a summary without the announcements source raises no announcement toast", async () => {
	const { calls, fetchItems: fetchUnseen } = fetcher({ count: 1, immediate: 1 });
	const toasts = [];
	const listener = toastUnseenImmediate({ fetchUnseen, show: (count) => toasts.push(count) });

	await listener({
		previous: null,
		summary: { sources: [{ key: "app.tasks", state: "ok", new_since: 3 }] },
	});

	assert.deepEqual(toasts, []);
	assert.deepEqual(calls, []);
});
