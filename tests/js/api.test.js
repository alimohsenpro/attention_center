import assert from "node:assert/strict";
import test from "node:test";

import { createApi } from "../../attention_center/public/js/attention_center/api.js";

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
