import assert from "node:assert/strict";
import test from "node:test";

import { fakeBrowser, settle, toneUrl } from "./fakes.js";

const ROLES = ["standard", "urgent", "immediate", "reminder"];
const LATER = "2026-11-11 10:00:00";
const EARLIER = "2026-11-11 08:00:00";

// Plays one alert in a single visible tab and returns what the tab played audibly.
async function playAlone(role, options = {}) {
	const browser = fakeBrowser();
	const tab = browser.open(options);
	await browser.play([[tab, role, "app.tasks#1@2026-11-11 08:59:00"]]);
	return tab.played;
}

// [role, the user's tone, the organisation's tones, the tone that plays].
const TONE_CASES = [
	["standard", "knock", {}, "knock"],
	["standard", "drop", {}, "drop"],
	["urgent", "knock", {}, "urgent"],
	["immediate", "knock", {}, "immediate"],
	["reminder", "knock", {}, "reminder"],
	["urgent", "knock", { urgent_tone: "telegraph" }, "telegraph"],
	["immediate", "knock", { immediate_tone: "pulse" }, "pulse"],
	["reminder", "knock", { reminder_tone: "chime" }, "chime"],
];

for (const [role, tone, organisation, expected] of TONE_CASES) {
	test(`the ${role} role plays ${expected} when the user's tone is ${tone} and the organisation chose ${JSON.stringify(
		organisation
	)}`, async () => {
		const settings = {
			urgent_tone: "urgent",
			immediate_tone: "immediate",
			reminder_tone: "reminder",
			...organisation,
		};

		const played = await playAlone(role, { prefs: { tone }, settings });

		assert.deepEqual(
			played.map((sound) => sound.url),
			[toneUrl(expected)]
		);
	});
}

// [the user's volume from 0 to 100, the audio element's volume from 0 to 1].
const VOLUME_CASES = [
	[100, 1],
	[60, 0.6],
	[25, 0.25],
	[1, 0.01],
];

for (const [volume, expected] of VOLUME_CASES) {
	test(`volume ${volume} plays at ${expected}`, async () => {
		const played = await playAlone("standard", { prefs: { volume } });

		assert.deepEqual(
			played.map((sound) => sound.volume),
			[expected]
		);
	});
}

test("volume 0 plays nothing, and shows no hint in a browser that blocks sound", async () => {
	const browser = fakeBrowser();
	const tab = browser.open({ prefs: { volume: 0 } });
	tab.refusal = "NotAllowedError";

	await browser.play([[tab, "immediate", "a"]]);
	tab.refusal = null;
	await browser.play([[tab, "immediate", "b"]]);

	assert.deepEqual(tab.played, []);
	assert.deepEqual(tab.locks, []);
});

test("a volume changed after a sound applies to the next one", async () => {
	const browser = fakeBrowser();
	const tab = browser.open({ prefs: { volume: 80 } });

	await browser.play([[tab, "standard", "a"]]);
	tab.prefs = { ...tab.prefs, volume: 30 };
	await browser.play([[tab, "standard", "b"]]);

	assert.deepEqual(
		tab.played.map((sound) => sound.volume),
		[0.8, 0.3]
	);
});

// [name, options of the tab, whether a sound plays]. User.mute_sounds and Do Not Disturb silence every role,
// including the urgent, immediate and reminder tones, which the sound scope never silences.
const MUTE_CASES = [
	["nothing silences it", {}, true],
	["User.mute_sounds is set", { muted: true }, false],
	["Do Not Disturb lasts", { prefs: { dnd_until: LATER } }, false],
	[
		"Do Not Disturb lasts, written with a T",
		{ prefs: { dnd_until: "2026-11-11T09:00:01" } },
		false,
	],
	[
		"User.mute_sounds is set and Do Not Disturb lasts",
		{ muted: true, prefs: { dnd_until: LATER } },
		false,
	],
	["Do Not Disturb has ended", { prefs: { dnd_until: EARLIER } }, true],
	[
		"User.mute_sounds is set after Do Not Disturb ended",
		{ muted: true, prefs: { dnd_until: EARLIER } },
		false,
	],
];

for (const role of ROLES) {
	for (const [name, options, audible] of MUTE_CASES) {
		test(`the ${role} tone ${audible ? "plays" : "is silent"} when ${name}`, async () => {
			const played = await playAlone(role, options);

			assert.equal(played.length, audible ? 1 : 0);
		});
	}
}

test("Do Not Disturb set after the page loaded silences the next sound", async () => {
	const browser = fakeBrowser();
	const tab = browser.open();

	await browser.play([[tab, "urgent", "a"]]);
	tab.prefs = { ...tab.prefs, dnd_until: LATER };
	await browser.play([[tab, "urgent", "b"]]);

	assert.equal(tab.played.length, 1);
});

test("a blocked sound locks the tab and shows the hint; the first gesture unlocks it without a reload", async () => {
	const browser = fakeBrowser();
	const tab = browser.open();
	tab.refusal = "NotAllowedError";

	await browser.play([[tab, "standard", "a"]]);
	assert.deepEqual(tab.played, []);
	assert.deepEqual(tab.locks, [true], "the hint is shown");

	// The user clicks: the browser allows sound from now on, and the page receives the gesture.
	tab.refusal = null;
	tab.page.dispatchEvent(new Event("pointerup"));
	await settle();
	assert.equal(tab.unlocks, 1);

	await browser.play([[tab, "urgent", "b"]]);
	assert.deepEqual(tab.played, [{ url: toneUrl("urgent"), volume: 0.6 }]);
	assert.deepEqual(tab.locks, [true]);
});

test("a locked tab does not try the next sounds until a gesture", async () => {
	const browser = fakeBrowser();
	const tab = browser.open();
	tab.refusal = "NotAllowedError";
	await browser.play([[tab, "standard", "a"]]);

	// The browser would allow the sound now, but the tab cannot know it before a gesture.
	tab.refusal = null;
	await browser.play([[tab, "immediate", "b"]]);

	assert.deepEqual(tab.played, []);
	assert.deepEqual(tab.locks, [true]);
	assert.equal(tab.unlocks, 0);
});

// [event the page receives, whether it unlocks the tab].
const GESTURE_CASES = [
	["pointerup", true],
	["keydown", true],
	["pointermove", false],
	["scroll", false],
];

for (const [type, unlocks] of GESTURE_CASES) {
	test(`${type} ${unlocks ? "unlocks" : "does not unlock"} a locked tab`, async () => {
		const browser = fakeBrowser();
		const tab = browser.open();
		tab.refusal = "NotAllowedError";
		await browser.play([[tab, "standard", "a"]]);

		tab.refusal = null;
		tab.page.dispatchEvent(new Event(type));
		await settle();
		await browser.play([[tab, "standard", "b"]]);

		assert.equal(tab.unlocks, unlocks ? 1 : 0);
		assert.equal(tab.played.length, unlocks ? 1 : 0);
	});
}

test("a gesture the browser does not count locks the tab again at the next sound, without a second hint", async () => {
	const browser = fakeBrowser();
	const tab = browser.open();
	tab.refusal = "NotAllowedError";
	await browser.play([[tab, "standard", "a"]]);

	// Escape: the muted tone plays, as it always does, but audible ones are still refused.
	tab.page.dispatchEvent(new Event("keydown"));
	await settle();
	await browser.play([[tab, "standard", "b"]]);
	assert.deepEqual(tab.locks, [true, false]);

	tab.refusal = null;
	tab.page.dispatchEvent(new Event("pointerup"));
	await settle();
	await browser.play([[tab, "standard", "c"]]);
	assert.deepEqual(tab.played, [{ url: toneUrl("knock"), volume: 0.6 }]);
});

test("an unlock that fails waits for the next gesture", async () => {
	const browser = fakeBrowser();
	const tab = browser.open();
	tab.refusal = "NotAllowedError";
	await browser.play([[tab, "standard", "a"]]);

	tab.mutedRefusal = "NotAllowedError";
	tab.page.dispatchEvent(new Event("pointerup"));
	await settle();
	assert.equal(tab.unlocks, 0);

	tab.refusal = null;
	tab.mutedRefusal = null;
	tab.page.dispatchEvent(new Event("pointerup"));
	await settle();
	await browser.play([[tab, "standard", "b"]]);
	assert.equal(tab.unlocks, 1);
	assert.equal(tab.played.length, 1);
	assert.deepEqual(tab.locks, [true]);
});

test("a tone that fails to load neither locks the tab nor fails the client", async () => {
	const browser = fakeBrowser();
	const tab = browser.open();
	tab.refusal = "NotSupportedError";

	await browser.play([[tab, "standard", "a"]]);
	tab.refusal = null;
	await browser.play([[tab, "standard", "b"]]);

	assert.deepEqual(tab.locks, []);
	assert.equal(tab.played.length, 1);
});
