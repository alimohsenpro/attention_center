import assert from "node:assert/strict";
import test from "node:test";

import { createGuard } from "../../attention_center/public/js/attention_center/util/guard.js";

function silenceErrors(t) {
	return t.mock.method(console, "error", () => {}).mock;
}

test("a throwing boot step is logged, undoes what it added and does not reach the desk", (t) => {
	const errors = silenceErrors(t);
	const guard = createGuard();
	const body = ["desk"];
	const failure = new Error("boot failed");

	const result = guard.run(() => {
		body.push("attention-center-root");
		guard.addCleanup(() => body.splice(body.indexOf("attention-center-root"), 1));
		throw failure;
	});

	assert.equal(result, undefined);
	assert.deepEqual(body, ["desk"]);
	assert.deepEqual(errors.calls.map((call) => call.arguments), [["[attention_center]", failure]]);
});

test("after a failure every wrapped handler does nothing for the rest of the page load", (t) => {
	silenceErrors(t);
	const guard = createGuard();
	const calls = [];
	const handler = guard.safe(() => calls.push("handled"));

	handler();
	guard.run(() => {
		throw new Error("render failed");
	});
	handler();
	guard.run(() => calls.push("run"));

	assert.deepEqual(calls, ["handled"]);
});

test("a rejected async handler is caught and turns the client off", async (t) => {
	const errors = silenceErrors(t);
	const guard = createGuard();
	const cleaned = [];
	guard.addCleanup(() => cleaned.push("host removed"));
	const failure = new Error("refresh failed");

	const result = await guard.safe(async () => {
		throw failure;
	})();

	assert.equal(result, undefined);
	assert.deepEqual(cleaned, ["host removed"]);
	assert.deepEqual(errors.calls[0].arguments, ["[attention_center]", failure]);
	assert.equal(guard.run(() => "still running"), undefined);
});

test("a failing cleanup is logged and the other cleanups still run", (t) => {
	const errors = silenceErrors(t);
	const guard = createGuard();
	const cleaned = [];
	const cleanupFailure = new Error("observer gone");
	guard.addCleanup(() => {
		throw cleanupFailure;
	});
	guard.addCleanup(() => cleaned.push("host removed"));

	guard.run(() => {
		throw new Error("boot failed");
	});

	assert.deepEqual(cleaned, ["host removed"]);
	assert.deepEqual(errors.calls[1].arguments, ["[attention_center]", cleanupFailure]);
});

test("cleanups run once, however many failures follow", (t) => {
	const errors = silenceErrors(t);
	const guard = createGuard();
	let cleanups = 0;
	guard.addCleanup(() => cleanups++);
	const late = guard.safe(async () => {
		throw new Error("late failure");
	});
	const pending = late();

	guard.run(() => {
		throw new Error("first failure");
	});

	return pending.then(() => {
		assert.equal(cleanups, 1);
		assert.equal(errors.calls.length, 2);
	});
});

test("a working handler gets its arguments and returns its result", async (t) => {
	const errors = silenceErrors(t);
	const guard = createGuard();
	let cleanups = 0;
	guard.addCleanup(() => cleanups++);

	assert.equal(guard.safe((a, b) => a + b)(2, 3), 5);
	assert.equal(await guard.safe(async (value) => value * 2)(21), 42);
	assert.equal(cleanups, 0);
	assert.equal(errors.calls.length, 0);
});
