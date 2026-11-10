import assert from "node:assert/strict";
import test from "node:test";

import {
	dndActive,
	newItemAlerts,
	reminderAlert,
} from "../../attention_center/public/js/attention_center/alerts/policy.js";

const ME = "me@example.com";
const COLLEAGUE = "colleague@example.com";
// The client's clock in the system time zone, as frappe.datetime.system_datetime() writes it.
const NOW = "2026-11-10 10:00:00";
const SCOPES = ["Urgent Only", "Action Items", "Everything"];

// A source of a summary as get_summary returns it; nothing pending unless the test says so.
function source(key, kind, counts = {}) {
	return {
		key,
		label: key,
		kind,
		count: 0,
		capped: false,
		urgent: 0,
		immediate: 0,
		overdue: 0,
		latest: null,
		new_since: 0,
		state: "ok",
		...counts,
	};
}

const summary = (...sources) => ({ sources });

function alertsFor({
	previous,
	next,
	actor = null,
	scope = "Action Items",
	dndUntil = null,
	now = NOW,
}) {
	return newItemAlerts({
		previous,
		summary: next,
		actor,
		user: ME,
		prefs: { sound_scope: scope, dnd_until: dndUntil },
		now,
	});
}

// One new item of each row of FR-ALERT-02, as the summaries before and after it arrived.
const EVENTS = {
	info: [
		summary(source("app.news", "info", { count: 2, latest: "2026-11-10T09:00:00" })),
		summary(source("app.news", "info", { count: 3, latest: "2026-11-10T09:58:00" })),
	],
	normal: [
		summary(source("app.tasks", "action", { count: 1, latest: "2026-11-10T09:00:00" })),
		summary(source("app.tasks", "action", { count: 2, latest: "2026-11-10T09:58:00" })),
	],
	urgent: [
		summary(source("app.tasks", "action", { count: 1, latest: "2026-11-10T09:00:00" })),
		summary(
			source("app.tasks", "action", { count: 2, urgent: 1, latest: "2026-11-10T09:58:00" })
		),
	],
	immediate: [
		summary(
			source("app.tasks", "action", { count: 1, urgent: 1, latest: "2026-11-10T09:00:00" })
		),
		summary(
			source("app.tasks", "action", {
				count: 2,
				urgent: 1,
				immediate: 1,
				latest: "2026-11-10T09:58:00",
			})
		),
	],
};

// FR-ALERT-02 for every sound scope: [event, scope, toast, sticky, sound].
const DECISION_TABLE = [
	["info", "Urgent Only", false, false, null],
	["info", "Action Items", false, false, null],
	["info", "Everything", false, false, "standard"],
	["normal", "Urgent Only", true, false, null],
	["normal", "Action Items", true, false, "standard"],
	["normal", "Everything", true, false, "standard"],
	["urgent", "Urgent Only", true, false, "urgent"],
	["urgent", "Action Items", true, false, "urgent"],
	["urgent", "Everything", true, false, "urgent"],
	["immediate", "Urgent Only", true, true, "immediate"],
	["immediate", "Action Items", true, true, "immediate"],
	["immediate", "Everything", true, true, "immediate"],
];

for (const [event, scope, toast, sticky, sound] of DECISION_TABLE) {
	test(`a new ${event} item with the sound scope "${scope}": toast ${toast}, sticky ${sticky}, sound ${sound}`, () => {
		const [previous, next] = EVENTS[event];

		assert.deepEqual(alertsFor({ previous, next, scope }), [
			{ source: next.sources[0].key, level: event, count: 1, toast, sticky, sound },
		]);
	});
}

for (const scope of SCOPES) {
	test(`the periodic reminder with the sound scope "${scope}": a toast and the reminder tone`, () => {
		assert.deepEqual(
			reminderAlert({ prefs: { sound_scope: scope, dnd_until: null }, now: NOW }),
			{
				level: "reminder",
				toast: true,
				sticky: false,
				sound: "reminder",
			}
		);
	});
}

for (const event of Object.keys(EVENTS)) {
	test(`the first summary of the page load raises no alert, even with a new ${event} item`, () => {
		const [, next] = EVENTS[event];

		assert.deepEqual(alertsFor({ previous: null, next, scope: "Everything" }), []);
	});

	test(`a new ${event} item the user caused raises no alert`, () => {
		const [previous, next] = EVENTS[event];

		assert.deepEqual(alertsFor({ previous, next, actor: ME, scope: "Everything" }), []);
	});

	test(`a new ${event} item a colleague caused, or of unknown cause, raises an alert`, () => {
		const [previous, next] = EVENTS[event];

		for (const actor of [COLLEAGUE, null]) {
			assert.equal(alertsFor({ previous, next, actor, scope: "Everything" }).length, 1);
		}
	});
}

// Do Not Disturb until `dndUntil`, at NOW.
const DND_CASES = [
	["until later today", "2026-11-10T11:00:00", true],
	["until one second from now", "2026-11-10T10:00:01", true],
	["that ended right now", "2026-11-10T10:00:00", false],
	["that ended an hour ago", "2026-11-10T09:00:00", false],
	["that ended yesterday", "2026-11-09T23:00:00", false],
	["off", null, false],
];

for (const [name, dndUntil, active] of DND_CASES) {
	test(`Do Not Disturb ${name} ${
		active ? "silences" : "leaves"
	} every sound and keeps every toast`, () => {
		for (const [event, , toast, , sound] of DECISION_TABLE.filter(
			(row) => row[1] === "Everything"
		)) {
			const [previous, next] = EVENTS[event];
			const [alert] = alertsFor({ previous, next, scope: "Everything", dndUntil });

			assert.equal(alert.toast, toast, event);
			assert.equal(alert.sound, active ? null : sound, event);
		}
		const reminder = reminderAlert({
			prefs: { sound_scope: "Everything", dnd_until: dndUntil },
			now: NOW,
		});
		assert.equal(reminder.toast, true);
		assert.equal(reminder.sound, active ? null : "reminder");
	});
}

test("Do Not Disturb compares times whichever separator the texts use", () => {
	assert.equal(dndActive("2026-11-10T10:30:00", "2026-11-10 10:00:00"), true);
	assert.equal(dndActive("2026-11-10 10:30:00", "2026-11-10T10:00:00"), true);
	assert.equal(dndActive("2026-11-10T09:30:00", "2026-11-10 10:00:00"), false);
});

const tasks = (counts) => summary(source("app.tasks", "action", counts));

// How many new items a change of one action source brings: [name, before, after, count].
const NEW_ITEM_CASES = [
	[
		"the count grew by three",
		{ count: 2, latest: "2026-11-10T09:00:00" },
		{ count: 5, latest: "2026-11-10T09:58:00" },
		3,
	],
	[
		"an item arrived as another was handled",
		{ count: 2, latest: "2026-11-10T09:00:00" },
		{ count: 2, latest: "2026-11-10T09:58:00" },
		1,
	],
	[
		"an item arrived as two were handled",
		{ count: 3, latest: "2026-11-10T09:00:00" },
		{ count: 2, latest: "2026-11-10T09:58:00" },
		1,
	],
	[
		"the count stayed at its cap and a newer item arrived",
		{ count: 99, capped: true, latest: "2026-11-10T09:00:00" },
		{ count: 99, capped: true, latest: "2026-11-10T09:58:00" },
		1,
	],
	["the first item arrived", { count: 0 }, { count: 1, latest: "2026-11-10T09:58:00" }, 1],
	[
		"a date-only source gained an item of the same day",
		{ count: 1, latest: "2026-11-10" },
		{ count: 2, latest: "2026-11-10" },
		1,
	],
	[
		"an item was handled",
		{ count: 2, latest: "2026-11-10T09:00:00" },
		{ count: 1, latest: "2026-11-10T09:00:00" },
		0,
	],
	[
		"the newest item was handled",
		{ count: 2, latest: "2026-11-10T09:58:00" },
		{ count: 1, latest: "2026-11-10T09:00:00" },
		0,
	],
	[
		"nothing changed",
		{ count: 2, latest: "2026-11-10T09:00:00" },
		{ count: 2, latest: "2026-11-10T09:00:00" },
		0,
	],
	[
		"an item became overdue",
		{ count: 2, overdue: 0, latest: "2026-11-10T09:00:00" },
		{ count: 2, overdue: 1, latest: "2026-11-10T09:00:00" },
		0,
	],
	[
		"the source failed before",
		{ state: "error" },
		{ count: 4, latest: "2026-11-10T09:58:00" },
		0,
	],
	["the source fails now", { count: 2, latest: "2026-11-10T09:00:00" }, { state: "error" }, 0],
];

for (const [name, before, after, count] of NEW_ITEM_CASES) {
	test(`new items when ${name}: ${count}`, () => {
		const alerts = alertsFor({ previous: tasks(before), next: tasks(after) });

		assert.deepEqual(
			alerts.map((alert) => alert.count),
			count ? [count] : []
		);
	});
}

test("a source that was not in the previous summary raises no alert", () => {
	const previous = summary(
		source("app.tasks", "action", { count: 1, latest: "2026-11-10T09:00:00" })
	);
	const next = summary(
		source("app.tasks", "action", { count: 1, latest: "2026-11-10T09:00:00" }),
		source("app.orders", "action", { count: 4, urgent: 2, latest: "2026-11-10T09:58:00" })
	);

	assert.deepEqual(alertsFor({ previous, next }), []);
});

// The level of a new action item comes from what grew with it: [name, before, after, level].
const LEVEL_CASES = [
	["only the count grew", { count: 1 }, { count: 2 }, "normal"],
	["the urgent count grew", { count: 1 }, { count: 2, urgent: 1 }, "urgent"],
	["the immediate count grew", { count: 1 }, { count: 2, immediate: 1 }, "immediate"],
	["both grew", { count: 1 }, { count: 3, urgent: 1, immediate: 1 }, "immediate"],
	[
		"an urgent item was handled as a normal one arrived",
		{ count: 2, urgent: 1 },
		{ count: 3, urgent: 0 },
		"normal",
	],
	["the overdue count grew with it", { count: 1 }, { count: 2, overdue: 1 }, "normal"],
];

for (const [name, before, after, level] of LEVEL_CASES) {
	test(`a new action item when ${name} is ${level}`, () => {
		const [alert] = alertsFor({ previous: tasks(before), next: tasks(after) });

		assert.equal(alert.level, level);
	});
}

test("each source that gained items raises its own alert, in summary order", () => {
	const previous = summary(
		source("app.tasks", "action", { count: 1 }),
		source("app.orders", "action", { count: 5, urgent: 1 }),
		source("app.news", "info", { count: 0 })
	);
	const next = summary(
		source("app.tasks", "action", { count: 3 }),
		source("app.orders", "action", { count: 5, urgent: 1 }),
		source("app.news", "info", { count: 2 })
	);

	assert.deepEqual(alertsFor({ previous, next, scope: "Everything" }), [
		{
			source: "app.tasks",
			level: "normal",
			count: 2,
			toast: true,
			sticky: false,
			sound: "standard",
		},
		{
			source: "app.news",
			level: "info",
			count: 2,
			toast: false,
			sticky: false,
			sound: "standard",
		},
	]);
});
