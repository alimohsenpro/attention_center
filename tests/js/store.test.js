import assert from "node:assert/strict";
import test from "node:test";

import { createStore } from "../../attention_center/public/js/attention_center/store.js";

test("set replaces the given keys and keeps the others", () => {
	const prefs = { launcher_collapsed: false };
	const store = createStore({ summary: null, prefs, ui: { open: false } });
	const summary = { totals: { action: 3 } };

	store.set({ summary });

	assert.deepEqual(store.get(), { summary, prefs, ui: { open: false } });
	assert.equal(store.get().prefs, prefs);
});

test("the initial object is not changed by later updates", () => {
	const initial = { summary: null };
	const store = createStore(initial);

	store.set({ summary: { totals: {} } });

	assert.deepEqual(initial, { summary: null });
});

test("listeners receive the new and the previous state", () => {
	const store = createStore({ summary: null, ui: { open: false } });
	const seen = [];
	store.subscribe((state, previous) => seen.push([previous.ui.open, state.ui.open]));

	store.set({ ui: { open: true } });
	store.set({ ui: { open: false } });

	assert.deepEqual(seen, [
		[false, true],
		[true, false],
	]);
});

test("an unsubscribed listener hears nothing more, the others still do", () => {
	const store = createStore({ count: 0 });
	const first = [];
	const second = [];
	const unsubscribe = store.subscribe((state) => first.push(state.count));
	store.subscribe((state) => second.push(state.count));

	store.set({ count: 1 });
	unsubscribe();
	store.set({ count: 2 });

	assert.deepEqual(first, [1]);
	assert.deepEqual(second, [1, 2]);
});

test("a listener that unsubscribes itself does not make the others miss the change", () => {
	const store = createStore({ count: 0 });
	const heard = [];
	const unsubscribe = store.subscribe(() => unsubscribe());
	store.subscribe((state) => heard.push(state.count));

	store.set({ count: 1 });

	assert.deepEqual(heard, [1]);
});
