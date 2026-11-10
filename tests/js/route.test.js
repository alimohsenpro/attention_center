import assert from "node:assert/strict";
import test from "node:test";

import {
	isDeskRoute,
	routeArguments,
} from "../../attention_center/public/js/attention_center/util/route.js";

const ACCEPTED = [
	"/app/todo",
	"/app/todo?status=Open",
	"/app/notification-log?read=0",
	"/app/sales-invoice/SINV-0001",
	"/app/my-request/REQ%2F0001",
	"/app/todo#comments",
];

const REJECTED = [
	["empty", ""],
	["not text", 42],
	["missing", undefined],
	["null", null],
	["an array", ["/app/todo"]],
	["relative", "app/todo"],
	["the desk root without a slash", "/app"],
	["another prefix", "/apps/todo"],
	["a longer word", "/application/todo"],
	["an API path", "/api/method/logout"],
	["an absolute URL", "https://example.com/app/todo"],
	["a protocol-relative URL", "//example.com/app/todo"],
	["a script URL", "javascript:alert(1)"],
	["a dot segment", "/app/../api/method/logout"],
	["an encoded dot segment", "/app/%2e%2e/api/method/logout"],
	["a backslash", "/app/\\example.com"],
	["a leading space", " /app/todo"],
	["a line break", "/app/todo\nx"],
	["a tab", "/app/to\tdo"],
	["a null character", "/app/todo\u0000"],
];

for (const route of ACCEPTED) {
	test(`desk route accepted: ${route}`, () => {
		assert.equal(isDeskRoute(route), true);
	});
}

for (const [name, route] of REJECTED) {
	test(`route rejected: ${name}`, () => {
		assert.equal(isDeskRoute(route), false);
	});
}

const ROUTE_ARGUMENTS = [
	["/app/todo", ["todo"]],
	["/app/todo?status=Open", ["todo", { status: "Open" }]],
	[
		"/app/notification-log?read=0&for_user=a%40example.com",
		["notification-log", { read: "0", for_user: "a@example.com" }],
	],
	["/app/sales-invoice/SINV-0001", ["sales-invoice", "SINV-0001"]],
	["/app/my-request/REQ%2F0001", ["my-request", "REQ/0001"]],
	["/app/my-request/%D8%B7%D9%84%D8%A8-1", ["my-request", "طلب-1"]],
	["/app/my-request/طلب-1", ["my-request", "طلب-1"]],
	["/app/todo/", ["todo"]],
	["/app/todo#comments", ["todo"]],
	["/app/my-request/100%", ["my-request", "100%"]],
	["/app/?status=Open", []],
];

for (const [route, expected] of ROUTE_ARGUMENTS) {
	test(`set_route arguments for ${route}`, () => {
		assert.deepEqual(routeArguments(route), expected);
	});
}
