import assert from "node:assert/strict";
import test from "node:test";

import {
	createApi,
	createTransport,
} from "../../attention_center/public/js/attention_center/api.js";

// A server whose answers the test releases one by one.
function fakeServer() {
	const requests = [];
	const call = (method, args) =>
		new Promise((resolve, reject) => requests.push({ method, args, resolve, reject }));
	return { requests, call };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

test("a summary request already on its way is shared instead of sent again", async () => {
	const server = fakeServer();
	const api = createApi(server.call);
	const summary = { totals: { action: 2 } };

	const first = api.getSummary();
	const second = api.getSummary();
	assert.equal(server.requests.length, 1);
	assert.equal(server.requests[0].method, "attention_center.api.get_summary");

	server.requests[0].resolve(summary);
	assert.equal(await first, summary);
	assert.equal(await second, summary);
});

test("once a summary request has settled, the next one goes to the server", async () => {
	const server = fakeServer();
	const api = createApi(server.call);

	const failed = api.getSummary();
	server.requests[0].reject(new Error("offline"));
	await assert.rejects(failed);
	const retried = api.getSummary();
	server.requests[1].resolve({ totals: {} });
	await retried;

	assert.equal(server.requests.length, 2);
});

test("preference writes are sent one after the other, in the order of the clicks", async () => {
	const server = fakeServer();
	const api = createApi(server.call);

	const collapse = api.setPreferences({ launcher_collapsed: true });
	const expand = api.setPreferences({ launcher_collapsed: false });
	await settle();
	assert.deepEqual(
		server.requests.map((request) => [request.method, request.args]),
		[["attention_center.api.set_preferences", { prefs: { launcher_collapsed: true } }]]
	);

	server.requests[0].resolve({ launcher_collapsed: true });
	assert.deepEqual(await collapse, { launcher_collapsed: true });
	await settle();
	assert.deepEqual(server.requests[1].args, { prefs: { launcher_collapsed: false } });
	server.requests[1].resolve({ launcher_collapsed: false });
	assert.deepEqual(await expand, { launcher_collapsed: false });
});

test("a failed write rejects its caller and does not block the next write", async () => {
	const server = fakeServer();
	const api = createApi(server.call);

	const failing = api.setPreferences({ launcher_collapsed: true });
	const next = api.setPreferences({ launcher_collapsed: false });
	await settle();
	server.requests[0].reject(new Error("server error"));
	await assert.rejects(failing, /server error/);
	await settle();
	server.requests[1].resolve({ launcher_collapsed: false });

	assert.deepEqual(await next, { launcher_collapsed: false });
});

test("an items request names the source and the page, and the same page asked twice is sent once", async () => {
	const server = fakeServer();
	const api = createApi(server.call);
	const page = { state: "ok", items: [], has_more: false };

	const first = api.getItems("app.tasks", 10, 10);
	const again = api.getItems("app.tasks", 10, 10);
	const other = api.getItems("app.tasks", 20, 10);

	assert.deepEqual(
		server.requests.map((request) => [request.method, request.args]),
		[
			[
				"attention_center.api.get_items",
				{ source: "app.tasks", start: 10, page_length: 10 },
			],
			[
				"attention_center.api.get_items",
				{ source: "app.tasks", start: 20, page_length: 10 },
			],
		]
	);
	server.requests[0].resolve(page);
	assert.equal(await first, page);
	assert.equal(await again, page);
	server.requests[1].resolve(page);
	await other;
});

test("marking sources seen is a write, queued behind the preference writes", async () => {
	const server = fakeServer();
	const api = createApi(server.call);

	const collapse = api.setPreferences({ launcher_collapsed: true });
	const seen = api.markSeen("app.tasks");
	await settle();
	assert.equal(server.requests.length, 1);

	server.requests[0].resolve({});
	await collapse;
	await settle();
	assert.deepEqual(
		[server.requests[1].method, server.requests[1].args],
		["attention_center.api.mark_seen", { source: "app.tasks" }]
	);
	server.requests[1].resolve(null);
	assert.equal(await seen, null);
});

// A fetch that records each request and gives every one the same answer.
function fakeFetch(status, body) {
	const requests = [];
	const fetch = async (url, init) => {
		requests.push({ url, init });
		return { ok: status >= 200 && status < 300, status, json: async () => body };
	};
	return { requests, fetch };
}

test("a call posts its arguments as JSON with the CSRF token and resolves to the method's result", async () => {
	const server = fakeFetch(200, { message: { launcher_collapsed: true } });
	const call = createTransport(server.fetch, () => "token-1");

	const result = await call("attention_center.api.set_preferences", {
		prefs: { launcher_collapsed: true },
	});

	assert.deepEqual(result, { launcher_collapsed: true });
	assert.equal(server.requests.length, 1);
	const [{ url, init }] = server.requests;
	assert.equal(url, "/api/method/attention_center.api.set_preferences");
	assert.equal(init.method, "POST");
	assert.equal(init.credentials, "same-origin");
	assert.equal(init.headers["Content-Type"], "application/json");
	assert.equal(init.headers["X-Frappe-CSRF-Token"], "token-1");
	assert.deepEqual(JSON.parse(init.body), { prefs: { launcher_collapsed: true } });
});

test("each call sends the CSRF token the desk holds at that moment", async () => {
	const server = fakeFetch(200, { message: null });
	let token = "before";
	const call = createTransport(server.fetch, () => token);

	await call("attention_center.api.get_summary", {});
	token = "after";
	await call("attention_center.api.get_summary", {});

	assert.deepEqual(
		server.requests.map((request) => request.init.headers["X-Frappe-CSRF-Token"]),
		["before", "after"]
	);
});

// The answers for which frappe.call opens a core dialog or the session-expired flow.
for (const status of [401, 403, 404, 417, 500, 502, 504, 508]) {
	test(`an HTTP ${status} answer rejects the call`, async () => {
		const server = fakeFetch(status, { exc_type: "SomeError", _server_messages: "[]" });
		const call = createTransport(server.fetch, () => "token");

		await assert.rejects(
			call("attention_center.api.get_summary", {}),
			new RegExp(`HTTP ${status}`)
		);
	});
}
