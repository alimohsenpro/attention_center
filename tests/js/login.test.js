import assert from "node:assert/strict";
import test from "node:test";

import { autoOpenOnLogin } from "../../attention_center/public/js/attention_center/alerts/login.js";
import { createStore } from "../../attention_center/public/js/attention_center/store.js";

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

function summary(...sources) {
	const sum = (kind, field) =>
		sources
			.filter((candidate) => candidate.kind === kind)
			.reduce((total, candidate) => total + candidate[field], 0);
	return {
		sources,
		totals: {
			action: sum("action", "count"),
			attention: 0,
			info_new: sum("info", "new_since"),
		},
	};
}

const WITH_ACTION = summary(
	source("app.tasks", "action", { count: 3, new_since: 2 }),
	source("app.orders", "action", { count: 1, new_since: 1 }),
	source("app.news", "info", { count: 5, new_since: 4 })
);
const INFO_ONLY = summary(source("app.news", "info", { count: 5, new_since: 4 }));

const settle = () => new Promise((resolve) => setImmediate(resolve));

// The server's side of a login session: whether the window opened by itself in it (note_auto_opened).
const newSession = () => ({ autoOpened: false });

// One page load of the desk in `session`: the boot's marker, the store with the effective preference, and a window
// that opens when asked, or fails to load. `receive(summary)` stores a summary as the refresh loop does.
function loadPage(session, { autoOpen = true, windowOpen = false, windowLoads = true } = {}) {
	const answers = [];
	const store = createStore(
		{ summary: null, prefs: { auto_open_on_login: autoOpen }, ui: { open: windowOpen } },
		() => answers.shift()
	);
	const page = {
		store,
		// The "new since you last looked" count of every time the window opened by itself.
		opened: [],
		async receive(next) {
			answers.push(Promise.resolve(next));
			await store.refreshSummary();
			await settle();
		},
		async fail() {
			answers.push(Promise.reject(new Error("offline")));
			await store.refreshSummary();
			await settle();
		},
	};
	store.onSummary(
		autoOpenOnLogin({
			shouldAutoOpen: !session.autoOpened,
			store,
			open: async (newSince) => {
				if (!windowLoads) return false;
				page.opened.push(newSince);
				store.set({ ui: { open: true, tab: null, newSince } });
				return true;
			},
			onOpened: () => (session.autoOpened = true),
		})
	);
	return page;
}

// [name, whether the session had its auto-open already, the auto_open_on_login preference, the first summary,
// whether the window opens].
const FIRST_SUMMARY = [
	["a new login session with action items opens the window", false, true, WITH_ACTION, true],
	["a session that had its auto-open already opens nothing", true, true, WITH_ACTION, false],
	["a user who turned auto-open off sees nothing open", false, false, WITH_ACTION, false],
	[
		"without action items nothing opens, whatever information is new",
		false,
		true,
		INFO_ONLY,
		false,
	],
];

for (const [name, autoOpened, autoOpen, first, opens] of FIRST_SUMMARY) {
	test(`at login, ${name}`, async () => {
		const session = { autoOpened };
		const page = loadPage(session, { autoOpen });

		await page.receive(first);

		assert.equal(page.store.get().ui.open, opens);
		assert.equal(page.opened.length, opens ? 1 : 0);
		assert.equal(session.autoOpened, autoOpened || opens, "the session records the auto-open");
	});
}

test("the window opens by itself once per login session", async () => {
	const session = newSession();
	const first = loadPage(session);
	await first.receive(WITH_ACTION);
	first.store.set({ ui: { open: false } });
	await first.receive(WITH_ACTION);
	await first.receive(summary(source("app.tasks", "action", { count: 7, new_since: 6 })));

	const reloaded = loadPage(session);
	await reloaded.receive(WITH_ACTION);

	assert.deepEqual([first.opened.length, reloaded.opened.length], [1, 0]);
	assert.equal(reloaded.store.get().ui.open, false);

	const nextLogin = loadPage(newSession());
	await nextLogin.receive(WITH_ACTION);
	assert.equal(nextLogin.opened.length, 1, "a new login session opens it again");
});

test("action items arriving after a first summary without any open nothing", async () => {
	const page = loadPage(newSession());

	await page.receive(INFO_ONLY);
	await page.receive(WITH_ACTION);

	assert.deepEqual(page.opened, []);
	assert.equal(page.store.get().ui.open, false);
});

test("the decision waits for the first summary that arrives, when the first request fails", async () => {
	const page = loadPage(newSession());

	await page.fail();
	assert.deepEqual(page.opened, []);
	await page.receive(WITH_ACTION);

	assert.equal(page.opened.length, 1);
});

test("the summary line counts the action items new since the user last looked, not the information", async () => {
	const page = loadPage(newSession());

	await page.receive(WITH_ACTION);

	assert.deepEqual(page.opened, [3]);
});

test("a window that fails to load is not recorded, so the next page load opens it", async () => {
	const session = newSession();
	const broken = loadPage(session, { windowLoads: false });
	await broken.receive(WITH_ACTION);
	assert.equal(session.autoOpened, false);

	const reloaded = loadPage(session);
	await reloaded.receive(WITH_ACTION);

	assert.equal(reloaded.opened.length, 1);
	assert.equal(session.autoOpened, true);
});

test("a window the user opened before the first summary is left as it is and counts as opened", async () => {
	const session = newSession();
	const page = loadPage(session, { windowOpen: true });

	await page.receive(WITH_ACTION);

	assert.deepEqual(page.opened, []);
	assert.deepEqual(page.store.get().ui, { open: true });
	assert.equal(session.autoOpened, true);
});
