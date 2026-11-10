import assert from "node:assert/strict";
import test from "node:test";

import {
	compareItems,
	createFeed,
	mergePage,
} from "../../attention_center/public/js/attention_center/util/feed.js";

const item = (id, fields = {}) => ({
	id,
	overdue: false,
	priority: "normal",
	date: "2026-11-01T09:00:00",
	...fields,
});
const ids = (entries) => entries.map(({ source, item }) => `${source}:${item.id}`);

const ORDER_CASES = [
	[
		"overdue before not overdue, whatever the priority",
		item("late", { overdue: true }),
		item("now", { priority: "immediate" }),
	],
	[
		"immediate before urgent",
		item("i", { priority: "immediate" }),
		item("u", { priority: "urgent" }),
	],
	["urgent before normal", item("u", { priority: "urgent" }), item("n")],
	[
		"newer before older in the same class",
		item("new", { date: "2026-11-02T08:00:00" }),
		item("old", { date: "2026-11-01T17:00:00" }),
	],
	[
		"a date-only item against a datetime of the day before",
		item("day", { date: "2026-11-02" }),
		item("time", { date: "2026-11-01T23:59:59" }),
	],
	["an item with a date before one without", item("dated"), item("undated", { date: null })],
	[
		"overdue and immediate before overdue and normal",
		item("a", { overdue: true, priority: "immediate" }),
		item("b", { overdue: true, date: "2026-11-09T00:00:00" }),
	],
];

for (const [name, first, second] of ORDER_CASES) {
	test(`items sort ${name}`, () => {
		assert.ok(compareItems(first, second) < 0);
		assert.ok(compareItems(second, first) > 0);
	});
}

test("items equal in class and date compare equal", () => {
	assert.equal(compareItems(item("a"), item("b")), 0);
});

test("the All tab merges the sources into one order and names each item's source", () => {
	const streams = [
		{
			key: "app.approvals",
			done: true,
			items: [
				item("a1", { priority: "urgent" }),
				item("a2", { date: "2026-10-01T00:00:00" }),
			],
		},
		{
			key: "app.tasks",
			done: true,
			items: [item("t1", { overdue: true }), item("t2", { date: "2026-11-05T00:00:00" })],
		},
	];

	const result = mergePage(streams, 0, 10);

	assert.deepEqual(result.need, []);
	assert.deepEqual(ids(result.items), [
		"app.tasks:t1",
		"app.approvals:a1",
		"app.tasks:t2",
		"app.approvals:a2",
	]);
	assert.equal(result.hasMore, false);
});

test("each source keeps its own order in the merge, even where the general order disagrees", () => {
	// Beyond its newest rows a source orders by date only (§4.4): its order is kept.
	const streams = [
		{
			key: "app.a",
			done: true,
			items: [item("old", { date: "2026-01-01" }), item("urgent", { priority: "urgent" })],
		},
		{ key: "app.b", done: true, items: [item("mid", { date: "2026-06-01" })] },
	];

	assert.deepEqual(ids(mergePage(streams, 0, 10).items), [
		"app.b:mid",
		"app.a:old",
		"app.a:urgent",
	]);
});

test("on a tie the earlier source goes first", () => {
	const streams = [
		{ key: "app.first", done: true, items: [item("x")] },
		{ key: "app.second", done: true, items: [item("y")] },
	];

	assert.deepEqual(ids(mergePage(streams, 0, 10).items), ["app.first:x", "app.second:y"]);
});

test("a page waits for every source whose fetched items are used up and may hold more", () => {
	const streams = [
		{ key: "app.a", done: false, items: [item("a1", { priority: "urgent" })] },
		{ key: "app.b", done: false, items: [] },
		{ key: "app.c", done: true, items: [] },
	];

	assert.deepEqual(mergePage(streams, 0, 2).need, ["app.b"]);

	streams[1].items.push(item("b1"));
	// a1 is placed; the second place could still be a2 or b1.
	assert.deepEqual(mergePage(streams, 0, 2).need, ["app.a"]);
});

test("a later page skips the items of the pages before it", () => {
	const streams = [
		{ key: "app.a", done: true, items: [item("1"), item("3", { date: "2026-10-01" })] },
		{
			key: "app.b",
			done: true,
			items: [item("2", { date: "2026-10-15" }), item("4", { date: "2026-09-01" })],
		},
	];

	assert.deepEqual(ids(mergePage(streams, 1, 2).items), ["app.a:3", "app.b:4"]);
	assert.equal(mergePage(streams, 1, 2).hasMore, false);
	assert.equal(mergePage(streams, 0, 2).hasMore, true);
});

const dated = (prefix, count) =>
	Array.from({ length: count }, (_, i) => item(`${prefix}${i}`, { date: `2026-10-0${9 - i}` }));

const HAS_MORE_CASES = [
	[
		"every source is done and the page used every item",
		[dated("a", 2), true],
		[dated("b", 1), true],
		false,
	],
	["fetched items are left after the page", [dated("a", 3), true], [dated("b", 1), true], true],
	// No request is needed to know it: the server said so with the items already fetched.
	[
		"a source used up exactly at the end of the page has more",
		[dated("a", 3), false],
		[[], true],
		true,
	],
];

for (const [name, [itemsA, doneA], [itemsB, doneB], expected] of HAS_MORE_CASES) {
	test(`a next page exists when ${name}: ${expected}`, () => {
		const streams = [
			{ key: "app.a", done: doneA, items: itemsA },
			{ key: "app.b", done: doneB, items: itemsB },
		];

		const result = mergePage(streams, 0, 3);

		assert.deepEqual(result.need, []);
		assert.equal(result.hasMore, expected);
	});
}

// A server holding the given items per source, answering pages like get_items, with a log of requests.
function fakeServer(itemsBySource, failing = new Set()) {
	const requests = [];
	const fetchItems = async (key, start, size) => {
		requests.push([key, start]);
		if (failing.has(key)) return { state: "error", items: [], has_more: false };
		const all = itemsBySource[key];
		return {
			state: "ok",
			items: all.slice(start, start + size),
			has_more: start + size < all.length,
		};
	};
	return { requests, fetchItems };
}

const series = (prefix, count, fields = {}) =>
	Array.from({ length: count }, (_, i) =>
		item(`${prefix}${i + 1}`, {
			date: `2026-11-${String(28 - i).padStart(2, "0")}T00:00:00`,
			...fields,
		})
	);

test("a source tab fetches its pages one at a time, and tells whether another follows", async () => {
	const server = fakeServer({ "app.tasks": series("t", 5) });
	const feed = createFeed(["app.tasks"], server.fetchItems, 2);

	const first = await feed.page(0);
	const second = await feed.page(1);
	const third = await feed.page(2);

	assert.deepEqual(ids(first.items), ["app.tasks:t1", "app.tasks:t2"]);
	assert.equal(first.hasMore, true);
	assert.deepEqual(ids(second.items), ["app.tasks:t3", "app.tasks:t4"]);
	assert.deepEqual(ids(third.items), ["app.tasks:t5"]);
	assert.equal(third.hasMore, false);
	assert.deepEqual(server.requests, [
		["app.tasks", 0],
		["app.tasks", 2],
		["app.tasks", 4],
	]);
});

test("going back to a page fetched before sends no request", async () => {
	const server = fakeServer({ "app.tasks": series("t", 5) });
	const feed = createFeed(["app.tasks"], server.fetchItems, 2);
	await feed.page(0);
	await feed.page(1);

	const again = await feed.page(0);

	assert.deepEqual(ids(again.items), ["app.tasks:t1", "app.tasks:t2"]);
	assert.equal(server.requests.length, 2);
});

test("the All tab fetches further only from the sources its page reaches into", async () => {
	const server = fakeServer({
		"app.urgent": series("u", 3, { priority: "urgent" }),
		"app.normal": series("n", 3),
	});
	const feed = createFeed(["app.urgent", "app.normal"], server.fetchItems, 2);

	const first = await feed.page(0);
	assert.deepEqual(ids(first.items), ["app.urgent:u1", "app.urgent:u2"]);
	assert.deepEqual(server.requests, [
		["app.urgent", 0],
		["app.normal", 0],
	]);

	const second = await feed.page(1);
	assert.deepEqual(ids(second.items), ["app.urgent:u3", "app.normal:n1"]);
	assert.deepEqual(server.requests.slice(2), [["app.urgent", 2]]);
	assert.equal(second.hasMore, true);

	const third = await feed.page(2);
	assert.deepEqual(ids(third.items), ["app.normal:n2", "app.normal:n3"]);
	assert.equal(third.hasMore, false);
});

test("a failing source is reported, and the other sources of the All tab still show", async () => {
	const server = fakeServer(
		{ "app.ok": series("o", 2), "app.broken": [] },
		new Set(["app.broken"])
	);
	const feed = createFeed(["app.broken", "app.ok"], server.fetchItems, 10);

	const page = await feed.page(0);

	assert.deepEqual(ids(page.items), ["app.ok:o1", "app.ok:o2"]);
	assert.deepEqual(page.failed, ["app.broken"]);
	assert.equal(page.hasMore, false);
});

test("a rejected request fails its source like an error state", async () => {
	const feed = createFeed(
		["app.tasks"],
		async () => {
			throw new Error("HTTP 502");
		},
		10
	);

	assert.deepEqual(await feed.page(0), { items: [], hasMore: false, failed: ["app.tasks"] });
});

test("retry asks a failed source again and keeps the items already fetched", async () => {
	const failing = new Set();
	const server = fakeServer({ "app.tasks": series("t", 3) }, failing);
	const feed = createFeed(["app.tasks"], server.fetchItems, 2);
	await feed.page(0);
	failing.add("app.tasks");
	assert.deepEqual((await feed.page(1)).failed, ["app.tasks"]);

	failing.clear();
	feed.retry();
	const page = await feed.page(1);

	assert.deepEqual(ids(page.items), ["app.tasks:t3"]);
	assert.deepEqual(page.failed, []);
	assert.deepEqual(server.requests, [
		["app.tasks", 0],
		["app.tasks", 2],
		["app.tasks", 2],
	]);
});

test("an item pushed onto the next page by a change in the source is shown once", async () => {
	const items = series("t", 4);
	const server = fakeServer({ "app.tasks": items });
	const feed = createFeed(["app.tasks"], server.fetchItems, 2);
	await feed.page(0);
	items.unshift(item("t0", { date: "2026-11-30T00:00:00" }));

	const page = await feed.page(1);

	assert.deepEqual(ids(page.items), ["app.tasks:t3", "app.tasks:t4"]);
	assert.deepEqual(server.requests, [
		["app.tasks", 0],
		["app.tasks", 2],
		["app.tasks", 4],
	]);
});

test("pages asked for at the same time share the request for a source", async () => {
	const server = fakeServer({ "app.tasks": series("t", 3) });
	const feed = createFeed(["app.tasks"], server.fetchItems, 2);

	const [first, again] = await Promise.all([feed.page(0), feed.page(0)]);

	assert.deepEqual(ids(first.items), ids(again.items));
	assert.deepEqual(server.requests, [["app.tasks", 0]]);
});

test("a source answering more but sending nothing ends instead of being asked forever", async () => {
	const requests = [];
	const feed = createFeed(
		["app.tasks"],
		async (key, start) => {
			requests.push(start);
			return { state: "ok", items: [], has_more: true };
		},
		2
	);

	const page = await feed.page(0);

	assert.deepEqual(page, { items: [], hasMore: false, failed: [] });
	assert.deepEqual(requests, [0]);
});
