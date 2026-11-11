import assert from "node:assert/strict";
import test from "node:test";

import { createStore } from "../../attention_center/public/js/attention_center/store.js";
import { sharePreferences } from "../../attention_center/public/js/attention_center/util/share_prefs.js";
import { fakeBroadcast, fakeClock } from "./fakes.js";

const USER = "clerk@example.com";
const PREFS = {
	sound_scope: "Action Items",
	volume: 60,
	dnd_until: null,
	launcher_collapsed: false,
};

// Opens a tab per user in one browser, each with the preferences of `initial` at its index; each records the
// messages it posts.
function openTabs(users, initial = users.map(() => PREFS)) {
	const clock = fakeClock();
	const channel = fakeBroadcast(clock);
	const tabs = users.map((user, index) => {
		const store = createStore({ summary: null, prefs: initial[index], ui: { open: false } });
		const tabChannel = channel();
		const posted = [];
		const post = tabChannel.postMessage;
		tabChannel.postMessage = (data) => {
			posted.push(data);
			post(data);
		};
		sharePreferences({ store, channel: tabChannel, user, safe: (fn) => fn });
		return { store, posted };
	});
	return { clock, tabs };
}

test("Do Not Disturb set in one tab applies in the user's other tabs", () => {
	const { clock, tabs } = openTabs([USER, USER, USER]);
	const prefs = { ...PREFS, dnd_until: "2026-11-11 10:00:00" };

	tabs[0].store.set({ prefs });
	clock.advance(10);

	for (const tab of tabs) assert.deepEqual(tab.store.get().prefs, prefs);
});

test("a tab that receives the preferences does not send them back", () => {
	const { clock, tabs } = openTabs([USER, USER]);

	tabs[0].store.set({ prefs: { ...PREFS, volume: 20 } });
	clock.advance(10);

	assert.equal(tabs[0].posted.length, 1);
	assert.deepEqual(tabs[1].posted, []);
});

test("the latest of two changes made in a row applies", () => {
	const { clock, tabs } = openTabs([USER, USER]);

	tabs[0].store.set({ prefs: { ...PREFS, volume: 20 } });
	tabs[0].store.set({ prefs: { ...PREFS, volume: 30 } });
	clock.advance(10);

	assert.equal(tabs[1].store.get().prefs.volume, 30);
});

test("a tab with older values changes only what the user changed in it", () => {
	// The second tab loaded after the volume was changed in another browser; the first still holds the old one.
	const newer = { ...PREFS, volume: 80 };
	const { clock, tabs } = openTabs([USER, USER], [PREFS, newer]);

	tabs[0].store.set({ prefs: { ...PREFS, dnd_until: "2026-11-11 10:00:00" } });
	clock.advance(10);

	assert.deepEqual(tabs[1].store.get().prefs, { ...newer, dnd_until: "2026-11-11 10:00:00" });
});

test("preferences set again to the values they hold send nothing", () => {
	const { clock, tabs } = openTabs([USER, USER]);

	tabs[0].store.set({ prefs: { ...PREFS } });
	clock.advance(10);

	assert.deepEqual(tabs[0].posted, []);
});

test("a tab of another user of the browser keeps its own preferences", () => {
	const { clock, tabs } = openTabs([USER, "manager@example.com"]);

	tabs[0].store.set({ prefs: { ...PREFS, volume: 0 } });
	clock.advance(10);

	assert.equal(tabs[1].store.get().prefs, PREFS);
});

test("a new summary or an opened window sends nothing", () => {
	const { clock, tabs } = openTabs([USER, USER]);

	tabs[0].store.set({ summary: { sources: [], totals: { action: 1 } } });
	tabs[0].store.set({ ui: { open: true } });
	clock.advance(10);

	assert.deepEqual(tabs[0].posted, []);
	assert.equal(tabs[1].store.get().prefs, PREFS);
});
