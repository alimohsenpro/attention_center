import assert from "node:assert/strict";
import test from "node:test";

import { alertId } from "../../attention_center/public/js/attention_center/alerts/tabs.js";
import { fakeBrowser, toneUrl } from "./fakes.js";

const ALERT = "app.tasks#3@2026-11-11 08:59:00";
const OTHER_ALERT = "app.orders#1@2026-11-11 08:59:30";

const playsPerTab = (tabs) => tabs.map((tab) => tab.played.length);

// [name, [visibility, random()] of each tab, the tabs that may be the one that plays].
const THREE_TABS = [
	[
		"a visible tab wins over two hidden ones",
		[
			["visible", 0.5],
			["hidden", 0.5],
			["hidden", 0.5],
		],
		[0],
	],
	[
		"a visible tab wins whichever tab it is",
		[
			["hidden", 0.5],
			["visible", 0.5],
			["hidden", 0.5],
		],
		[1],
	],
	[
		"a visible tab wins over hidden tabs with the shortest delay",
		[
			["hidden", 0],
			["hidden", 0],
			["visible", 0.99],
		],
		[2],
	],
	[
		"of three hidden tabs, the one with the shortest delay wins",
		[
			["hidden", 0.7],
			["hidden", 0.2],
			["hidden", 0.9],
		],
		[1],
	],
	[
		"of three hidden tabs with the same delay, one wins",
		[
			["hidden", 0.5],
			["hidden", 0.5],
			["hidden", 0.5],
		],
		[0, 1, 2],
	],
	[
		"of two visible tabs (two windows side by side), one wins",
		[
			["visible", 0.5],
			["visible", 0.5],
			["hidden", 0.5],
		],
		[0, 1],
	],
];

for (const [name, tabs, winners] of THREE_TABS) {
	test(`exactly one of three tabs plays an alert: ${name}`, async () => {
		const browser = fakeBrowser({ storageLatencyMs: 2 });
		const opened = tabs.map(([visibility, random]) => browser.open({ visibility, random }));

		await browser.play(opened.map((tab) => [tab, "urgent", ALERT]));

		const plays = playsPerTab(opened);
		assert.equal(plays.filter((count) => count === 1).length, 1, `plays per tab: ${plays}`);
		assert.equal(plays.filter((count) => count > 1).length, 0, `plays per tab: ${plays}`);
		assert.ok(winners.includes(plays.indexOf(1)), `plays per tab: ${plays}`);
	});
}

test("two tabs that claim at the same moment, unseen by each other, agree on the later claim", async () => {
	// Each claim reaches the other tab only after both were written, and the channel is slower still.
	const browser = fakeBrowser({ storageLatencyMs: 5, channelLatencyMs: 10 });
	const first = browser.open({ visibility: "hidden", random: 0.5 });
	const second = browser.open({ visibility: "hidden", random: 0.5 });

	await browser.play([
		[first, "standard", ALERT],
		[second, "standard", ALERT],
	]);

	assert.deepEqual(playsPerTab([first, second]), [0, 1]);
});

test("a claim heard on the channel keeps a tab silent before the claim reaches its storage", async () => {
	const browser = fakeBrowser({ storageLatencyMs: 1000, channelLatencyMs: 1 });
	const visible = browser.open({ visibility: "visible" });
	const hidden = browser.open({ visibility: "hidden", random: 0 });

	await browser.play([
		[visible, "urgent", ALERT],
		[hidden, "urgent", ALERT],
	]);

	assert.deepEqual(playsPerTab([visible, hidden]), [1, 0]);
});

// A tab fetches a change later than another after a broadcast's random wait (up to 5 s) or a slow request.
for (const delay of [300, 5000, 29000]) {
	test(`a tab that fetches the alert ${delay} ms after another tab played it stays silent`, async () => {
		const browser = fakeBrowser();
		const first = browser.open({ visibility: "hidden", random: 0.5 });
		const late = browser.open({ visibility: "visible" });

		await browser.play([[first, "urgent", ALERT]], delay);
		await browser.play([[late, "urgent", ALERT]]);

		assert.deepEqual(playsPerTab([first, late]), [1, 0]);
	});
}

test("a tab does not play the same alert twice", async () => {
	const browser = fakeBrowser();
	const tab = browser.open();

	await browser.play([[tab, "standard", ALERT]]);
	await browser.play([[tab, "standard", ALERT]]);

	assert.equal(tab.played.length, 1);
});

test("different alerts at the same moment each play once, in the visible tab", async () => {
	const browser = fakeBrowser({ storageLatencyMs: 2 });
	const tabs = [
		browser.open({ visibility: "hidden", random: 0.1 }),
		browser.open({ visibility: "visible" }),
		browser.open({ visibility: "hidden", random: 0.9 }),
	];

	await browser.play(
		tabs.flatMap((tab) => [
			[tab, "urgent", ALERT],
			[tab, "immediate", OTHER_ALERT],
		])
	);

	assert.deepEqual(
		tabs.map((tab) => tab.played.map((sound) => sound.url).sort()),
		[[], [toneUrl("immediate"), toneUrl("urgent")].sort(), []]
	);
});

test("a tab that marks an alert plays nothing, and a tab that fetches the alert later stays silent", async () => {
	const browser = fakeBrowser();
	const marking = browser.open({ visibility: "hidden" });
	const late = browser.open({ visibility: "visible" });

	marking.mark(ALERT);
	await browser.play([[late, "standard", ALERT]]);

	assert.deepEqual(playsPerTab([marking, late]), [0, 0]);
});

test("a claim is forgotten after 30 s and removed from the storage at the next claim", async () => {
	const browser = fakeBrowser();
	const tab = browser.open();
	const late = browser.open();

	await browser.play([[tab, "standard", ALERT]], 30000);
	await browser.play([[late, "standard", OTHER_ALERT]]);

	assert.deepEqual(
		Array.from({ length: late.storage.length }, (_, index) => late.storage.key(index)),
		[`attention_center:claim:${OTHER_ALERT}`]
	);
});

const source = (key, count, latest) => ({
	key,
	kind: "action",
	state: "ok",
	count,
	latest,
	urgent: 0,
	immediate: 0,
	overdue: 0,
});
const alert = (key, count, sound) => ({
	source: key,
	level: sound ? "normal" : "info",
	count,
	toast: Boolean(sound),
	sticky: false,
	sound,
});
const SUMMARY = {
	sources: [
		source("app.tasks", 5, "2026-11-11 08:59:00"),
		source("app.orders", 2, "2026-11-11 08:58:00"),
		source("app.news", 7, "2026-11-11 08:57:00"),
	],
};

test("tabs whose previous summaries differ give the same change the same id", () => {
	// One tab had 4 tasks before this summary; another, whose refresh came later, had 3.
	assert.equal(
		alertId([alert("app.tasks", 1, "standard")], SUMMARY),
		alertId([alert("app.tasks", 2, "standard")], SUMMARY)
	);
});

test("the id names each source whose alert sounds, with its count and latest date, in a fixed order", () => {
	const tasks = alert("app.tasks", 1, "standard");
	const orders = alert("app.orders", 1, "urgent");
	const news = alert("app.news", 3, null);

	assert.equal(
		alertId([tasks, orders, news], SUMMARY),
		"app.orders#2@2026-11-11 08:58:00 app.tasks#5@2026-11-11 08:59:00"
	);
	assert.equal(alertId([news, orders, tasks], SUMMARY), alertId([tasks, orders], SUMMARY));
});

test("alerts that play no sound give no id", () => {
	assert.equal(alertId([alert("app.news", 3, null)], SUMMARY), "");
});

// [name, the source in the summary after the change].
const CHANGE_CASES = [
	["its count grows", source("app.tasks", 6, "2026-11-11 08:59:00")],
	["its count stays while its latest date grows", source("app.tasks", 5, "2026-11-11 09:00:00")],
	["it has no latest date", source("app.tasks", 6, null)],
];

for (const [name, changed] of CHANGE_CASES) {
	test(`a later change of a source gets another id when ${name}`, () => {
		const before = alertId([alert("app.tasks", 1, "standard")], SUMMARY);
		const after = alertId([alert("app.tasks", 1, "standard")], { sources: [changed] });

		assert.notEqual(after, before);
	});
}
