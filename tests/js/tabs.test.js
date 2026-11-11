import assert from "node:assert/strict";
import test from "node:test";

import { alertId } from "../../attention_center/public/js/attention_center/alerts/tabs.js";
import { fakeBrowser, settle, toneUrl } from "./fakes.js";

const ALERT = "app.tasks#3@2026-11-11 08:59:00";
// The next change of the same source, which a tab whose burst already sounded coalesces.
const LATER_ALERT = "app.tasks#4@2026-11-11 08:59:40";
const OTHER_ALERT = "app.orders#1@2026-11-11 08:59:30";

const playsPerTab = (tabs) => tabs.map((tab) => tab.played.length);
const storedClaims = (tab) =>
	Array.from({ length: tab.storage.length }, (_, index) => tab.storage.key(index));

// A sound refused before the user's first gesture: the tab knows it is locked from then on.
async function lockEarlier(browser, tab) {
	tab.refusal = "NotAllowedError";
	await browser.play([[tab, "standard", "app.notes#1@2026-11-11 08:50:00"]]);
}

// Long enough for a tab that has not shown it can play to claim an alert and play it.
const FRESH_MS = 3000;

// A tab opened in the background or reloaded, and not clicked since: the browser refuses its sound, which the tab
// cannot know before it tries one.
function openBlocked(browser, options) {
	const tab = browser.open({ active: false, ...options });
	tab.refusal = "NotAllowedError";
	return tab;
}

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

// [name, [visibility, random(), whether the page had a gesture] of each tab, the tab that plays]. Every tab's
// browser lets it play: the order in which the tabs claim decides.
const FRESH_TABS = [
	[
		"a hidden tab that had a gesture wins over a fresh visible tab",
		[
			["visible", 0.5, false],
			["hidden", 0.99, true],
		],
		[1],
	],
	[
		"a hidden tab that had a gesture wins over a fresh hidden tab with a shorter delay",
		[
			["hidden", 0, false],
			["hidden", 0.99, true],
		],
		[1],
	],
	[
		"among tabs that had a gesture, the visible one still wins",
		[
			["visible", 0.5, false],
			["hidden", 0, true],
			["visible", 0.99, true],
		],
		[2],
	],
	[
		"of fresh tabs only, the visible one wins",
		[
			["hidden", 0, false],
			["visible", 0.5, false],
			["hidden", 0.5, false],
		],
		[1],
	],
	[
		"of three fresh hidden tabs with the same delay, one wins",
		[
			["hidden", 0.5, false],
			["hidden", 0.5, false],
			["hidden", 0.5, false],
		],
		[0, 1, 2],
	],
];

for (const [name, tabs, winners] of FRESH_TABS) {
	test(`exactly one tab plays an alert: ${name}`, async () => {
		const browser = fakeBrowser({ storageLatencyMs: 2 });
		const opened = tabs.map(([visibility, random, active]) =>
			browser.open({ visibility, random, active })
		);

		await browser.play(
			opened.map((tab) => [tab, "urgent", ALERT]),
			FRESH_MS
		);

		const plays = playsPerTab(opened);
		assert.equal(plays.filter((count) => count === 1).length, 1, `plays per tab: ${plays}`);
		assert.equal(plays.filter((count) => count > 1).length, 0, `plays per tab: ${plays}`);
		assert.ok(winners.includes(plays.indexOf(1)), `plays per tab: ${plays}`);
	});
}

// [name, options of the tab the browser blocks].
const BLOCKED_BESIDE_ABLE = [
	["visible", { visibility: "visible" }],
	["hidden, with a shorter delay", { visibility: "hidden", random: 0 }],
];

for (const [name, options] of BLOCKED_BESIDE_ABLE) {
	test(`a fresh tab the browser blocks (${name}) leaves the alert to a hidden tab that can play, and shows no hint`, async () => {
		const browser = fakeBrowser({ storageLatencyMs: 2 });
		const blocked = openBlocked(browser, options);
		const able = browser.open({ visibility: "hidden", random: 0.99 });

		await browser.play(
			[
				[blocked, "immediate", ALERT],
				[able, "immediate", ALERT],
			],
			FRESH_MS
		);

		assert.deepEqual(playsPerTab([blocked, able]), [0, 1]);
		assert.deepEqual(blocked.locks, []);
	});
}

test("a hidden tab that can play claims first even when it fetches the alert 2 s after a fresh tab", async () => {
	// The browser runs a hidden tab's timers up to about a second late: the refresh that fetches the change,
	// then the claim's delay.
	const browser = fakeBrowser();
	const blocked = openBlocked(browser, { visibility: "visible" });
	const able = browser.open({ visibility: "hidden", random: 0.99 });

	const first = blocked.sound.alert("immediate", ALERT);
	browser.clock.advance(2000);
	await browser.play([[able, "immediate", ALERT]], FRESH_MS);
	await first;

	assert.deepEqual(playsPerTab([blocked, able]), [0, 1]);
	assert.deepEqual(blocked.locks, []);
});

test("a fresh tab alone still claims the alert: the browser refuses it, and the hint shows", async () => {
	const browser = fakeBrowser();
	const blocked = openBlocked(browser, { visibility: "hidden" });

	await browser.play([[blocked, "immediate", ALERT]], FRESH_MS);

	assert.deepEqual(blocked.played, []);
	assert.deepEqual(blocked.locks, [true]);
});

test("a fresh tab alone that the browser lets play plays the alert", async () => {
	const browser = fakeBrowser();
	const fresh = browser.open({ visibility: "hidden", active: false });

	await browser.play([[fresh, "immediate", ALERT]], FRESH_MS);

	assert.deepEqual(
		fresh.played.map((sound) => sound.url),
		[toneUrl("immediate")]
	);
});

test("a fresh tab refused after it claimed gives the alert back to a tab that can play and fetches it later", async () => {
	// A broadcast's random wait (§6) lets a tab fetch the change seconds after another.
	const browser = fakeBrowser();
	const blocked = openBlocked(browser, { visibility: "visible" });
	const able = browser.open({ visibility: "hidden" });

	await browser.play([[blocked, "immediate", ALERT]], FRESH_MS);
	browser.clock.advance(1000);
	await browser.play([[able, "immediate", ALERT]]);

	assert.deepEqual(blocked.locks, [true]);
	assert.deepEqual(playsPerTab([blocked, able]), [0, 1]);
	assert.equal(storedClaims(able).length, 1);
});

test("a fresh tab that played a sound claims at once from then on, and wins as the visible tab", async () => {
	const browser = fakeBrowser();
	const fresh = browser.open({ visibility: "visible", active: false });
	await browser.play([[fresh, "standard", OTHER_ALERT]], FRESH_MS);
	const hidden = browser.open({ visibility: "hidden", random: 0 });

	await browser.play([
		[fresh, "urgent", ALERT],
		[hidden, "urgent", ALERT],
	]);

	assert.deepEqual(playsPerTab([fresh, hidden]), [2, 0]);
});

test("a fresh tab clicked since it loaded claims at once, and wins as the visible tab", async () => {
	const browser = fakeBrowser();
	const fresh = browser.open({ visibility: "visible", active: false });
	const hidden = browser.open({ visibility: "hidden", random: 0 });
	fresh.activation.hasBeenActive = true;

	await browser.play([
		[fresh, "urgent", ALERT],
		[hidden, "urgent", ALERT],
	]);

	assert.deepEqual(playsPerTab([fresh, hidden]), [1, 0]);
});

test("with the storage full, each alert still plays in one tab, which the channel tells the others, and nothing fails", async () => {
	const browser = fakeBrowser();
	const visible = browser.open({ visibility: "visible" });
	const hidden = browser.open({ visibility: "hidden" });
	visible.storage.full = true;
	hidden.storage.full = true;

	await browser.play([
		[visible, "urgent", ALERT],
		[hidden, "urgent", ALERT],
	]);
	await browser.play([[visible, null, LATER_ALERT]]);
	await browser.play([[hidden, "immediate", OTHER_ALERT]]);

	assert.deepEqual(
		[visible, hidden].map((tab) => tab.played.map((sound) => sound.url)),
		[[toneUrl("urgent")], [toneUrl("immediate")]]
	);
});

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

test("a tab whose burst sounded plays nothing for the burst's later alert, and a tab that fetches it later stays silent", async () => {
	const browser = fakeBrowser();
	const sounding = browser.open({ visibility: "hidden" });
	const late = browser.open({ visibility: "visible" });

	await browser.play([[sounding, "urgent", ALERT]], 2000);
	await browser.play([[sounding, null, LATER_ALERT]], 1000);
	await browser.play([[late, "urgent", LATER_ALERT]]);

	assert.deepEqual(playsPerTab([sounding, late]), [1, 0]);
});

test("a tab whose burst another tab sounded keeps a later fetch of the burst's later alert silent too", async () => {
	const browser = fakeBrowser();
	const visible = browser.open({ visibility: "visible" });
	const hidden = browser.open({ visibility: "hidden" });
	const late = browser.open({ visibility: "hidden" });

	await browser.play(
		[
			[visible, "urgent", ALERT],
			[hidden, "urgent", ALERT],
		],
		2000
	);
	await browser.play([[hidden, null, LATER_ALERT]], 1000);
	await browser.play([[late, "urgent", LATER_ALERT]]);

	assert.deepEqual(playsPerTab([visible, hidden, late]), [1, 0, 0]);
});

// [name, options of the tab whose burst is silent, what happened to it before the burst]. Another tab, after a
// longer broadcast wait (§6), fetches the whole burst in one summary and must play it.
const SILENT_BURSTS = [
	["User.mute_sounds is set", { muted: true }, async () => {}],
	["Do Not Disturb lasts", { prefs: { dnd_until: "2026-11-11 10:00:00" } }, async () => {}],
	["the volume is 0", { prefs: { volume: 0 } }, async () => {}],
	["an earlier sound locked the tab", {}, lockEarlier],
	[
		"the browser refuses the burst's first sound",
		{},
		async (browser, tab) => (tab.refusal = "NotAllowedError"),
	],
];

for (const [name, options, before] of SILENT_BURSTS) {
	test(`a tab whose burst is silent because ${name} leaves the burst's later alert to another tab`, async () => {
		const browser = fakeBrowser();
		const silent = browser.open({ visibility: "visible", ...options });
		const other = browser.open({ visibility: "hidden" });
		await before(browser, silent);

		await browser.play([[silent, "urgent", ALERT]], 2000);
		await browser.play([[silent, null, LATER_ALERT]], 1000);
		await browser.play([[other, "urgent", LATER_ALERT]]);

		assert.deepEqual(playsPerTab([silent, other]), [0, 1]);
	});
}

test("a tab unlocked by a gesture during its silent burst still leaves the burst's later alert to another tab", async () => {
	const browser = fakeBrowser();
	const unlocked = browser.open({ visibility: "visible" });
	const other = browser.open({ visibility: "hidden" });
	await lockEarlier(browser, unlocked);

	await browser.play([[unlocked, "urgent", ALERT]], 2000);
	unlocked.refusal = null;
	unlocked.page.dispatchEvent(new Event("pointerup"));
	await settle();
	await browser.play([[unlocked, null, LATER_ALERT]], 1000);
	await browser.play([[other, "urgent", LATER_ALERT]]);

	assert.equal(unlocked.unlocks, 1);
	assert.deepEqual(playsPerTab([unlocked, other]), [0, 1]);
});

test("a summary whose alerts play no sound records no claim", async () => {
	const browser = fakeBrowser();
	const tab = browser.open();

	await browser.play([[tab, "urgent", ALERT]]);
	await browser.play([[tab, null, ""]]);

	assert.equal(storedClaims(tab).length, 1);
});

test("a claim is forgotten after 30 s and removed from the storage at the next claim", async () => {
	const browser = fakeBrowser();
	const tab = browser.open();
	const late = browser.open();

	await browser.play([[tab, "standard", ALERT]], 30000);
	await browser.play([[late, "standard", OTHER_ALERT]]);

	assert.equal(storedClaims(late).length, 1);
});

test("the claims left in the storage name no source, count or date", async () => {
	const browser = fakeBrowser();
	const tab = browser.open();

	await browser.play([[tab, "standard", ALERT]]);

	const claims = storedClaims(tab);
	assert.equal(claims.length, 1);
	for (const text of [...claims, ...claims.map((name) => tab.storage.getItem(name))]) {
		assert.doesNotMatch(text, /app\.tasks|#3|2026/);
	}
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
