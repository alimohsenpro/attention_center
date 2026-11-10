import assert from "node:assert/strict";
import test from "node:test";

import {
	NUDGE_EVENT,
	startRefreshLoop,
} from "../../attention_center/public/js/attention_center/realtime.js";
import { createStore } from "../../attention_center/public/js/attention_center/store.js";

const ME = "me@example.com";
const COLLEAGUE = "colleague@example.com";
const HOUR_MS = 3600 * 1000;

// A clock the test moves by hand; the timers due within a step run in the order of their time.
function fakeClock() {
	let time = 0;
	let nextId = 1;
	const timers = new Map();
	return {
		now: () => time,
		setTimeout(callback, ms) {
			timers.set(nextId, { at: time + ms, callback });
			return nextId++;
		},
		clearTimeout: (id) => timers.delete(id),
		advance(ms) {
			const end = time + ms;
			for (;;) {
				let due = null;
				for (const [id, timer] of timers) {
					if (timer.at <= end && (!due || timer.at < due.at)) due = { id, ...timer };
				}
				if (!due) break;
				timers.delete(due.id);
				time = due.at;
				due.callback();
			}
			time = end;
		},
		// Moves the clock to an absolute time.
		to(at) {
			this.advance(at - time);
		},
	};
}

// frappe.realtime as the loop uses it: handlers registered with on, and the socket's events.
function fakeRealtime() {
	const handlers = new Map();
	return {
		on: (event, handler) => handlers.set(event, [...(handlers.get(event) ?? []), handler]),
		emit: (event, payload) => {
			for (const handler of handlers.get(event) ?? []) handler(payload);
		},
	};
}

function fakePage(visibilityState) {
	const page = new EventTarget();
	page.visibilityState = visibilityState;
	page.setVisibility = (state) => {
		page.visibilityState = state;
		page.dispatchEvent(new Event("visibilitychange"));
	};
	return page;
}

// Starts a loop whose refreshes are recorded with their time and actor, unless the test brings its own.
function startLoop({
	heartbeatSeconds = 300,
	visibility = "visible",
	random = () => 0,
	refresh,
} = {}) {
	const clock = fakeClock();
	const realtime = fakeRealtime();
	const page = fakePage(visibility);
	const network = new EventTarget();
	const requests = [];
	startRefreshLoop({
		refresh: refresh ?? ((actor) => requests.push({ at: clock.now(), actor })),
		heartbeatSeconds,
		realtime,
		page,
		network,
		safe: (fn) => fn,
		clock,
		random,
	});
	return { clock, realtime, page, network, requests };
}

const times = (requests) => requests.map((request) => request.at);
const nudge = (actor) => ({ sources: ["app.tasks"], actor });
const broadcast = () => ({ sources: ["app.tasks"], broadcast: true });

test("the first refresh comes after the start, not during it", () => {
	const { clock, requests } = startLoop();
	assert.deepEqual(requests, []);

	clock.advance(1499);
	assert.deepEqual(requests, []);
	clock.advance(1);
	assert.deepEqual(requests, [{ at: 1500, actor: null }]);
});

test("a burst of nudges sends one request, 1.5 s after the last", () => {
	const { clock, realtime, requests } = startLoop();
	clock.to(10000);
	requests.length = 0;

	for (const at of [10000, 10400, 10800, 11200]) {
		clock.to(at);
		realtime.emit(NUDGE_EVENT, nudge(COLLEAGUE));
	}
	clock.to(12699);
	assert.deepEqual(requests, []);
	clock.to(20000);

	assert.deepEqual(requests, [{ at: 12700, actor: COLLEAGUE }]);
});

test("a steady stream of nudges still refreshes 5 s after the first of each burst", () => {
	const { clock, realtime, requests } = startLoop();
	clock.to(10000);
	requests.length = 0;

	for (let at = 10000; at <= 21000; at += 1000) {
		clock.to(at);
		realtime.emit(NUDGE_EVENT, nudge(COLLEAGUE));
	}
	clock.to(30000);

	assert.deepEqual(times(requests), [15000, 20000, 22500]);
});

for (const random of [0, 0.5, 0.999]) {
	test(`a burst of broadcasts waits a random ${random * 5} s, then the debounce, and sends one request`, () => {
		const { clock, realtime, requests } = startLoop({ random: () => random });
		clock.to(10000);
		requests.length = 0;

		realtime.emit(NUDGE_EVENT, broadcast());
		clock.advance(Math.floor((random * 5000) / 2));
		realtime.emit(NUDGE_EVENT, broadcast());
		clock.to(30000);

		assert.deepEqual(requests, [{ at: 10000 + random * 5000 + 1500, actor: null }]);
	});
}

// What happens to a started loop, as the browser and the socket deliver it.
const nudgedBy =
	(actor) =>
	({ realtime }) =>
		realtime.emit(NUDGE_EVENT, nudge(actor));
const broadcastReceived = ({ realtime }) => realtime.emit(NUDGE_EVENT, broadcast());
const socketConnects = ({ realtime }) => realtime.emit("connect");
const backOnline = ({ network }) => network.dispatchEvent(new Event("online"));
const becomesVisible = ({ page }) => {
	page.setVisibility("hidden");
	page.setVisibility("visible");
};

// The refresh names the actor of the nudges it answers only when they all name the same one.
const ACTOR_CASES = [
	["one nudge", [nudgedBy(ME)], ME],
	["two nudges by the same user", [nudgedBy(ME), nudgedBy(ME)], ME],
	["nudges by two users", [nudgedBy(ME), nudgedBy(COLLEAGUE)], null],
	["a nudge and a broadcast", [nudgedBy(ME), broadcastReceived], null],
	["a nudge and the browser back online", [nudgedBy(ME), backOnline], null],
	["a nudge and the socket connecting", [nudgedBy(ME), socketConnects], null],
	["a broadcast", [broadcastReceived], null],
];

for (const [name, events, actor] of ACTOR_CASES) {
	test(`the actor of the refresh after ${name}`, () => {
		const loop = startLoop();
		loop.clock.to(10000);
		loop.requests.length = 0;

		for (const happen of events) happen(loop);
		loop.clock.to(20000);

		assert.deepEqual(
			loop.requests.map((request) => request.actor),
			[actor]
		);
	});
}

// A broadcast that waits out its random delay (4.5 s here) brings a change the user did not make: a request
// sent meanwhile carries that change, so it names no actor even when it answers only the user's own nudges.
const BROADCAST_WAIT_CASES = [
	[
		"a broadcast, then the user's nudge during its wait",
		[
			[10000, broadcastReceived],
			[10500, nudgedBy(ME)],
		],
		[
			{ at: 12000, actor: null },
			{ at: 16000, actor: null },
		],
	],
	[
		"the user's nudge, then a broadcast before its request",
		[
			[10000, nudgedBy(ME)],
			[10500, broadcastReceived],
		],
		[
			{ at: 11500, actor: null },
			{ at: 16500, actor: null },
		],
	],
	[
		"the user's nudge, its request, then a broadcast",
		[
			[10000, nudgedBy(ME)],
			[12000, broadcastReceived],
		],
		[
			{ at: 11500, actor: ME },
			{ at: 18000, actor: null },
		],
	],
	[
		"a broadcast, its request, then the user's nudge",
		[
			[10000, broadcastReceived],
			[17000, nudgedBy(ME)],
		],
		[
			{ at: 16000, actor: null },
			{ at: 18500, actor: ME },
		],
	],
];

for (const [name, events, expected] of BROADCAST_WAIT_CASES) {
	test(`the actors of the refreshes after ${name}`, () => {
		const loop = startLoop({ random: () => 0.9 });
		loop.clock.to(10000);
		loop.requests.length = 0;

		for (const [at, happen] of events) {
			loop.clock.to(at);
			happen(loop);
		}
		loop.clock.to(30000);

		assert.deepEqual(loop.requests, expected);
	});
}

const OTHER_TRIGGERS = [
	["the socket connects again", socketConnects],
	["the browser is back online", backOnline],
	["the page becomes visible", becomesVisible],
];

for (const [name, fire] of OTHER_TRIGGERS) {
	test(`a refresh follows 1.5 s after ${name}`, () => {
		const loop = startLoop();
		loop.clock.to(10000);
		loop.requests.length = 0;

		fire(loop);
		loop.clock.to(20000);

		assert.deepEqual(times(loop.requests), [11500]);
	});
}

for (const heartbeatSeconds of [60, 300]) {
	test(`a visible page refreshes every ${heartbeatSeconds} s, the configured heartbeat`, () => {
		const { clock, requests } = startLoop({ heartbeatSeconds });
		const beat = heartbeatSeconds * 1000;

		clock.to(3 * beat + 1499);
		assert.deepEqual(times(requests), [1500, beat + 1500, 2 * beat + 1500]);
		clock.advance(1);
		assert.deepEqual(times(requests), [1500, beat + 1500, 2 * beat + 1500, 3 * beat + 1500]);
	});
}

test("a page hidden from the start fetches the first summary and does not poll", () => {
	const { clock, requests } = startLoop({ heartbeatSeconds: 60, visibility: "hidden" });

	clock.to(HOUR_MS);

	assert.deepEqual(times(requests), [1500]);
});

test("a hidden page stops polling, and refreshes and polls again once visible", () => {
	const { clock, page, requests } = startLoop({ heartbeatSeconds: 60 });
	clock.to(10000);
	page.setVisibility("hidden");

	clock.to(HOUR_MS);
	assert.deepEqual(times(requests), [1500]);

	page.setVisibility("visible");
	clock.to(HOUR_MS + 60000 + 1500);
	assert.deepEqual(times(requests), [1500, HOUR_MS + 1500, HOUR_MS + 60000 + 1500]);
});

test("a hidden page still refreshes on a nudge, so that its alerts can play", () => {
	const { clock, realtime, requests } = startLoop({ visibility: "hidden" });
	clock.to(HOUR_MS);

	realtime.emit(NUDGE_EVENT, nudge(COLLEAGUE));
	clock.to(2 * HOUR_MS);

	assert.deepEqual(requests, [
		{ at: 1500, actor: null },
		{ at: HOUR_MS + 1500, actor: COLLEAGUE },
	]);
});

const settle = () => new Promise((resolve) => setImmediate(resolve));

test("triggers while a summary request is on its way send no second request, and one more follows it", async () => {
	const answers = [];
	const store = createStore(
		{ summary: null },
		() => new Promise((resolve) => answers.push(resolve))
	);
	const { clock, realtime, network } = startLoop({ refresh: store.refreshSummary });
	clock.to(1500);
	assert.equal(answers.length, 1);

	realtime.emit(NUDGE_EVENT, nudge(COLLEAGUE));
	clock.advance(1500);
	network.dispatchEvent(new Event("online"));
	clock.advance(1500);
	assert.equal(answers.length, 1);

	answers[0]({ totals: { action: 1 } });
	await settle();
	assert.equal(answers.length, 2);
	answers[1]({ totals: { action: 2 } });
	await settle();

	assert.equal(answers.length, 2);
	assert.deepEqual(store.get().summary, { totals: { action: 2 } });
});
