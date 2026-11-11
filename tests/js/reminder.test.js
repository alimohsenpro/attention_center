import assert from "node:assert/strict";
import test from "node:test";

import {
	LAST_REMINDER_KEY,
	startReminder,
} from "../../attention_center/public/js/attention_center/alerts/reminder.js";
import { createStore } from "../../attention_center/public/js/attention_center/store.js";
import { fakeClock, fakeStorage } from "./fakes.js";

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
// The current time as the policy reads it, naive ISO text in the system time zone.
const NOW = "2026-11-11 09:00:00";

// A summary with this many attention items (urgent, immediate or overdue) among its action items.
const summary = (attention) => ({
	sources: [],
	totals: { action: attention + 2, attention, info_new: 0 },
});

// A browser whose tabs share a clock and localStorage; each tab runs the reminder on its own store.
function fakeBrowser({ intervalHours = 2, storageLatencyMs = 0 } = {}) {
	const clock = fakeClock();
	const storage = fakeStorage(clock, storageLatencyMs);
	return {
		clock,
		// What an earlier page stored: the time of its last reminder.
		seed: (at) => storage().setItem(LAST_REMINDER_KEY, String(at)),
		stored: () => storage().getItem(LAST_REMINDER_KEY),
		// Opens a tab now. `attention` is the attention count of its summary, or null before its first summary.
		open({ visibility = "visible", attention = 1, prefs = {} } = {}) {
			const tab = {
				store: createStore({
					summary: attention === null ? null : summary(attention),
					prefs: { dnd_until: null, ...prefs },
					ui: { open: false },
				}),
				page: { visibilityState: visibility },
				storage: storage(),
				// The alerts the tab reminded with, and when.
				reminders: [],
				setAttention(count) {
					this.store.set({ summary: summary(count) });
				},
			};
			tab.reminder = startReminder({
				intervalHours,
				store: tab.store,
				storage: tab.storage,
				page: tab.page,
				systemNow: () => NOW,
				remind: (alert) => tab.reminders.push({ at: clock.now(), ...alert }),
				safe: (fn) => fn,
				clock,
			});
			return tab;
		},
	};
}

const times = (tab) => tab.reminders.map((reminder) => reminder.at);

test("the first check starts the interval, and a reminder follows every interval while attention items wait", () => {
	const browser = fakeBrowser();
	const tab = browser.open();

	browser.clock.advance(MINUTE_MS);
	assert.deepEqual(times(tab), [], "the first check reminds of nothing");
	assert.equal(browser.stored(), String(MINUTE_MS));

	browser.clock.advance(2 * HOUR_MS - 1);
	assert.deepEqual(times(tab), []);
	browser.clock.advance(1);
	assert.deepEqual(times(tab), [2 * HOUR_MS + MINUTE_MS]);

	browser.clock.advance(4 * HOUR_MS);
	assert.deepEqual(times(tab), [2, 4, 6].map((hours) => hours * HOUR_MS + MINUTE_MS));
	assert.deepEqual(
		tab.reminders.map(({ level, toast, sticky, sound }) => ({ level, toast, sticky, sound })),
		Array(3).fill({ level: "reminder", toast: true, sticky: false, sound: "reminder" })
	);
	assert.deepEqual(tab.store.get().ui, { open: false }, "a reminder never opens the window");
});

// [name, the tabs as [visibility, when they open], the tabs that may remind].
const TABS = [
	[
		"a visible tab reminds, not the hidden tabs opened after it",
		[
			["visible", 0],
			["hidden", 17000],
			["hidden", 42000],
		],
		[0],
	],
	[
		"a visible tab reminds, not the hidden tabs opened before it, whose checks come first",
		[
			["hidden", 0],
			["hidden", 17000],
			["visible", 42000],
		],
		[2],
	],
	[
		"with no visible tab, a hidden tab reminds",
		[
			["hidden", 0],
			["hidden", 17000],
			["hidden", 42000],
		],
		[0, 1, 2],
	],
];

for (const [name, specs, reminding] of TABS) {
	test(`one reminder per interval in the whole browser: ${name}`, () => {
		const browser = fakeBrowser();
		const tabs = [];
		for (const [visibility, at] of specs) {
			browser.clock.advance(at - browser.clock.now());
			tabs.push(browser.open({ visibility }));
		}

		browser.clock.advance(7 * HOUR_MS);

		const all = tabs.flatMap(times).sort((a, b) => a - b);
		assert.equal(all.length, 3);
		for (let index = 1; index < all.length; index++) {
			const gap = all[index] - all[index - 1];
			assert.ok(gap >= 2 * HOUR_MS && gap <= 2 * HOUR_MS + 3 * MINUTE_MS, `gap of ${gap} ms`);
		}
		tabs.forEach((tab, index) => {
			if (!reminding.includes(index)) assert.deepEqual(times(tab), [], `tab ${index} reminded`);
		});
	});
}

test("a hidden tab reminds only two minutes after the reminder is due", () => {
	const browser = fakeBrowser();
	const tab = browser.open({ visibility: "hidden" });

	browser.clock.advance(2 * HOUR_MS + 3 * MINUTE_MS - 1);
	assert.deepEqual(times(tab), []);
	browser.clock.advance(1);

	assert.deepEqual(times(tab), [2 * HOUR_MS + 3 * MINUTE_MS]);
});

test("a page loaded later keeps the browser's interval instead of starting a new one", () => {
	const browser = fakeBrowser();
	browser.clock.advance(HOUR_MS);
	browser.seed(HOUR_MS);
	browser.clock.advance(90 * MINUTE_MS);

	const tab = browser.open();
	browser.clock.advance(2 * HOUR_MS);

	assert.deepEqual(times(tab), [3 * HOUR_MS]);
});

test("a page loaded long after the last reminder reminds at its first check", () => {
	const browser = fakeBrowser();
	browser.clock.advance(HOUR_MS);
	browser.seed(HOUR_MS);
	browser.clock.advance(15 * HOUR_MS);

	const tab = browser.open();
	browser.clock.advance(MINUTE_MS);

	assert.deepEqual(times(tab), [16 * HOUR_MS + MINUTE_MS]);
});

test("no reminder comes while no attention items wait", () => {
	const browser = fakeBrowser();
	const tab = browser.open({ attention: 0 });

	browser.clock.advance(10 * HOUR_MS);

	assert.deepEqual(times(tab), []);
	assert.equal(browser.stored(), null);
});

test("attention items that appear start the interval, instead of bringing a reminder at once", () => {
	const browser = fakeBrowser();
	browser.clock.advance(HOUR_MS);
	browser.seed(HOUR_MS);
	const tab = browser.open({ attention: 0 });
	browser.clock.advance(4 * HOUR_MS);

	tab.setAttention(1);
	browser.clock.advance(3 * HOUR_MS);

	assert.deepEqual(times(tab), [7 * HOUR_MS + MINUTE_MS]);
});

test("attention items handled and back again start a new interval", () => {
	const browser = fakeBrowser();
	const tab = browser.open();
	browser.clock.advance(90 * MINUTE_MS);
	tab.setAttention(0);
	browser.clock.advance(30 * MINUTE_MS);

	tab.setAttention(2);
	browser.clock.advance(150 * MINUTE_MS);

	assert.deepEqual(times(tab), [4 * HOUR_MS + MINUTE_MS]);
});

test("a tab waits for its first summary before it checks", () => {
	const browser = fakeBrowser();
	const tab = browser.open({ attention: null });

	browser.clock.advance(10 * MINUTE_MS);
	assert.equal(browser.stored(), null);
	tab.setAttention(1);
	browser.clock.advance(MINUTE_MS);

	assert.equal(browser.stored(), String(11 * MINUTE_MS));
	assert.deepEqual(times(tab), []);
});

test("restarting the interval, as the login auto-open does, puts the next reminder a full interval later", () => {
	const browser = fakeBrowser();
	const tab = browser.open();
	browser.clock.advance(HOUR_MS);

	tab.reminder.restart();
	browser.clock.advance(3 * HOUR_MS);

	assert.deepEqual(times(tab), [3 * HOUR_MS]);
});

test("during Do Not Disturb the reminder still shows its toast, without a tone", () => {
	const browser = fakeBrowser();
	const tab = browser.open({ prefs: { dnd_until: "2026-11-11 10:00:00" } });

	browser.clock.advance(2 * HOUR_MS + MINUTE_MS);

	assert.deepEqual(
		tab.reminders.map(({ toast, sound }) => ({ toast, sound })),
		[{ toast: true, sound: null }]
	);
});

test("an interval of 0 turns the reminder off", () => {
	const browser = fakeBrowser({ intervalHours: 0 });
	const tab = browser.open();

	tab.reminder.restart();
	browser.clock.advance(10 * HOUR_MS);

	assert.deepEqual(times(tab), []);
	assert.equal(browser.stored(), null);
});

test("when the storage refuses writes, a tab still reminds once per interval, not at every check", () => {
	const browser = fakeBrowser();
	const tab = browser.open();
	tab.storage.full = true;

	browser.clock.advance(5 * HOUR_MS);

	assert.deepEqual(times(tab), [2 * HOUR_MS + MINUTE_MS, 4 * HOUR_MS + MINUTE_MS]);
});

test("tabs that remind at the same moment claim the same sound, and successive reminders differ", () => {
	// Each tab sees the other's write only 100 ms later, and their checks are 50 ms apart.
	const browser = fakeBrowser({ storageLatencyMs: 100 });
	browser.clock.advance(HOUR_MS);
	browser.seed(HOUR_MS);
	browser.clock.advance(100);
	const first = browser.open();
	browser.clock.advance(50);
	const second = browser.open();

	browser.clock.advance(5 * HOUR_MS);

	const [firstRace, ...firstLater] = first.reminders;
	const [secondRace, ...secondLater] = second.reminders;
	assert.deepEqual([firstRace.at, secondRace.at], [3 * HOUR_MS + 100, 3 * HOUR_MS + 150]);
	assert.equal(firstRace.id, secondRace.id);
	const later = [...firstLater, ...secondLater];
	assert.equal(later.length, 1, "the next interval has one reminder again");
	assert.notEqual(later[0].id, firstRace.id);
});
