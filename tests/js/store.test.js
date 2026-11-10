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

// A server whose summary answers the test gives one by one; a summary is { n } for the nth request.
function fakeServer() {
	const requests = [];
	const getSummary = () =>
		new Promise((resolve, reject) => requests.push({ resolve, reject }));
	const answer = (index) => requests[index].resolve({ n: index + 1 });
	return { requests, getSummary, answer };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

test("a refreshed summary is stored and handed to the alert layer with the previous one and the actor", async () => {
	const server = fakeServer();
	const store = createStore({ summary: null, ui: { open: false } }, server.getSummary);
	const changes = [];
	const states = [];
	store.onSummary((change) => changes.push(change));
	store.subscribe((state) => states.push(state.summary));

	const first = store.refreshSummary();
	server.answer(0);
	await first;
	const second = store.refreshSummary("colleague@example.com");
	server.answer(1);
	await second;

	assert.deepEqual(store.get(), { summary: { n: 2 }, ui: { open: false } });
	assert.deepEqual(states, [{ n: 1 }, { n: 2 }]);
	assert.deepEqual(changes, [
		{ previous: null, summary: { n: 1 }, actor: null },
		{ previous: { n: 1 }, summary: { n: 2 }, actor: "colleague@example.com" },
	]);
});

test("a failed summary request keeps the summary, tells no one, and the next refresh asks again", async () => {
	const server = fakeServer();
	const store = createStore({ summary: { n: 0 } }, server.getSummary);
	const heard = [];
	store.subscribe(() => heard.push("state"));
	store.onSummary(() => heard.push("summary"));

	const failed = store.refreshSummary();
	server.requests[0].reject(new Error("HTTP 502"));
	await failed;
	assert.deepEqual(store.get().summary, { n: 0 });
	assert.deepEqual(heard, []);

	const retried = store.refreshSummary();
	server.answer(1);
	await retried;
	assert.deepEqual(store.get().summary, { n: 2 });
});

test("refreshes asked while a request is on its way share one request sent after it", async () => {
	const server = fakeServer();
	const store = createStore({ summary: null }, server.getSummary);

	const first = store.refreshSummary();
	const waiting = [store.refreshSummary(), store.refreshSummary(), store.refreshSummary()];
	await settle();
	assert.equal(server.requests.length, 1);

	let shared = false;
	Promise.all(waiting).then(() => (shared = true));
	server.answer(0);
	assert.equal(await first, undefined);
	assert.deepEqual(store.get().summary, { n: 1 });
	await settle();
	assert.equal(server.requests.length, 2);
	assert.equal(shared, false);

	server.answer(1);
	await Promise.all(waiting);
	assert.deepEqual(store.get().summary, { n: 2 });
	await settle();
	assert.equal(server.requests.length, 2);
});

test("a request that fails still lets the refresh asked meanwhile go", async () => {
	const server = fakeServer();
	const store = createStore({ summary: null }, server.getSummary);

	store.refreshSummary();
	const waiting = store.refreshSummary();
	server.requests[0].reject(new Error("offline"));
	await settle();
	server.answer(1);
	await waiting;

	assert.deepEqual(store.get().summary, { n: 2 });
});

test("a summary listener that throws still lets the refresh asked meanwhile go, and later ones too", async () => {
	const server = fakeServer();
	const store = createStore({ summary: null }, server.getSummary);
	let failing = true;
	store.onSummary(() => {
		if (failing) {
			failing = false;
			throw new Error("listener");
		}
	});

	const first = store.refreshSummary();
	const waiting = store.refreshSummary();
	server.answer(0);
	await assert.rejects(first);
	await settle();
	assert.equal(server.requests.length, 2);

	const later = store.refreshSummary();
	server.answer(1);
	await waiting;
	await settle();
	assert.equal(server.requests.length, 3);
	server.answer(2);
	await later;

	assert.deepEqual(store.get().summary, { n: 3 });
});

// The refreshes asked while a request is on its way, and the actor their shared request reports.
const FOLLOW_UP_ACTORS = [
	[["me@example.com"], "me@example.com"],
	[["me@example.com", "me@example.com"], "me@example.com"],
	[["me@example.com", "colleague@example.com"], null],
	[["me@example.com", null], null],
	[[null, "me@example.com"], null],
	[[null], null],
];

for (const [actors, expected] of FOLLOW_UP_ACTORS) {
	test(`refreshes asked meanwhile by ${JSON.stringify(actors)} report the actor ${expected}`, async () => {
		const server = fakeServer();
		const store = createStore({ summary: null }, server.getSummary);
		const reported = [];
		store.onSummary(({ actor }) => reported.push(actor));

		store.refreshSummary("colleague@example.com");
		const waiting = actors.map((actor) => store.refreshSummary(actor));
		server.answer(0);
		await settle();
		server.answer(1);
		await Promise.all(waiting);

		assert.deepEqual(reported, ["colleague@example.com", expected]);
	});
}
