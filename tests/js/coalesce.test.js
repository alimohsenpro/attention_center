import assert from "node:assert/strict";
import test from "node:test";

import { coalesce } from "../../attention_center/public/js/attention_center/alerts/coalesce.js";

const WINDOW_MS = 10000;

// Alerts as newItemAlerts returns them, with the sound each would play alone.
const normal = (source, count = 1, sound = "standard") => ({
	source,
	level: "normal",
	count,
	toast: true,
	sticky: false,
	sound,
});
const urgent = (source, count = 1, sound = "urgent") => ({
	source,
	level: "urgent",
	count,
	toast: true,
	sticky: false,
	sound,
});
const immediate = (source, count = 1, sound = "immediate") => ({
	source,
	level: "immediate",
	count,
	toast: true,
	sticky: true,
	sound,
});
const info = (source, count = 1, sound = null) => ({
	source,
	level: "info",
	count,
	toast: false,
	sticky: false,
	sound,
});

// Feeds the summaries' alerts, [time, alerts], one after the other and collects what each one shows and plays.
function run(steps) {
	let burst = null;
	return steps.map(([now, alerts]) => {
		const result = coalesce(burst, alerts, now, WINDOW_MS);
		burst = result.burst;
		return { toast: result.toast, sound: result.sound };
	});
}

const toast = (id, count, level, source = null, sticky = level === "immediate") => ({
	id,
	count,
	level,
	sticky,
	source,
});

// [name, steps, what each step shows and plays].
const BURSTS = [
	[
		"one new item",
		[[0, [normal("app.tasks")]]],
		[{ toast: toast(1, 1, "normal", "app.tasks"), sound: "standard" }],
	],
	[
		"items of one source in one summary",
		[[0, [normal("app.tasks", 4)]]],
		[{ toast: toast(1, 4, "normal", "app.tasks"), sound: "standard" }],
	],
	[
		"items of two sources in one summary: the highest level and its sound",
		[[0, [normal("app.tasks", 2), urgent("app.orders")]]],
		[{ toast: toast(1, 3, "urgent"), sound: "urgent" }],
	],
	[
		"two summaries of one source inside the window",
		[
			[0, [normal("app.tasks")]],
			[6000, [normal("app.tasks", 2)]],
		],
		[
			{ toast: toast(1, 1, "normal", "app.tasks"), sound: "standard" },
			{ toast: toast(1, 3, "normal", "app.tasks"), sound: null },
		],
	],
	[
		"a burst rising to immediate: the toast becomes sticky and the higher sound plays once",
		[
			[0, [normal("app.tasks")]],
			[2000, [immediate("app.orders")]],
			[4000, [urgent("app.orders")]],
			[6000, [normal("app.tasks")]],
		],
		[
			{ toast: toast(1, 1, "normal", "app.tasks"), sound: "standard" },
			{ toast: toast(1, 2, "immediate"), sound: "immediate" },
			{ toast: toast(1, 3, "immediate"), sound: null },
			{ toast: toast(1, 4, "immediate"), sound: null },
		],
	],
	[
		"a burst of urgent items sounds once",
		[
			[0, [urgent("app.orders")]],
			[3000, [urgent("app.orders")]],
			[9000, [urgent("app.orders")]],
		],
		[
			{ toast: toast(1, 1, "urgent", "app.orders"), sound: "urgent" },
			{ toast: toast(1, 2, "urgent", "app.orders"), sound: null },
			{ toast: toast(1, 3, "urgent", "app.orders"), sound: null },
		],
	],
	[
		"an immediate item first: later ones neither lower the toast nor sound again",
		[
			[0, [immediate("app.orders")]],
			[1000, [normal("app.tasks"), urgent("app.orders")]],
		],
		[
			{ toast: toast(1, 1, "immediate", "app.orders"), sound: "immediate" },
			{ toast: toast(1, 3, "immediate"), sound: null },
		],
	],
	[
		"an item at the last moment of the window joins the burst; one at its end starts another",
		[
			[0, [normal("app.tasks")]],
			[9999, [normal("app.tasks")]],
			[10000, [normal("app.tasks")]],
		],
		[
			{ toast: toast(1, 1, "normal", "app.tasks"), sound: "standard" },
			{ toast: toast(1, 2, "normal", "app.tasks"), sound: null },
			{ toast: toast(2, 1, "normal", "app.tasks"), sound: "standard" },
		],
	],
	[
		"the window counts from the first alert of the burst, not the last",
		[
			[0, [normal("app.tasks")]],
			[8000, [normal("app.tasks")]],
			[12000, [urgent("app.orders")]],
		],
		[
			{ toast: toast(1, 1, "normal", "app.tasks"), sound: "standard" },
			{ toast: toast(1, 2, "normal", "app.tasks"), sound: null },
			{ toast: toast(2, 1, "urgent", "app.orders"), sound: "urgent" },
		],
	],
	[
		"silent new information starts no burst",
		[
			[0, [info("app.news")]],
			[9000, [normal("app.tasks")]],
			[15000, [normal("app.tasks")]],
		],
		[
			{ toast: null, sound: null },
			{ toast: toast(1, 1, "normal", "app.tasks"), sound: "standard" },
			{ toast: toast(1, 2, "normal", "app.tasks"), sound: null },
		],
	],
	[
		"new information that sounds (scope everything) takes the burst's one standard sound, and no toast",
		[
			[0, [info("app.news", 2, "standard")]],
			[3000, [normal("app.tasks")]],
		],
		[
			{ toast: null, sound: "standard" },
			{ toast: toast(1, 1, "normal", "app.tasks"), sound: null },
		],
	],
	[
		"information beside action items counts neither in the toast nor as its source",
		[[0, [info("app.news", 3, "standard"), normal("app.tasks")]]],
		[{ toast: toast(1, 1, "normal", "app.tasks"), sound: "standard" }],
	],
	[
		"silent alerts (scope urgent only) show toasts, and a later urgent item still sounds",
		[
			[0, [normal("app.tasks", 1, null)]],
			[2000, [urgent("app.orders")]],
		],
		[
			{ toast: toast(1, 1, "normal", "app.tasks"), sound: null },
			{ toast: toast(1, 2, "urgent"), sound: "urgent" },
		],
	],
	[
		"Do Not Disturb: every toast, no sound",
		[
			[0, [normal("app.tasks", 1, null)]],
			[2000, [immediate("app.orders", 1, null)]],
		],
		[
			{ toast: toast(1, 1, "normal", "app.tasks"), sound: null },
			{ toast: toast(1, 2, "immediate"), sound: null },
		],
	],
	[
		"no alerts change nothing, inside the window or after it",
		[
			[0, [urgent("app.orders")]],
			[5000, []],
			[7000, [urgent("app.orders")]],
			[20000, []],
		],
		[
			{ toast: toast(1, 1, "urgent", "app.orders"), sound: "urgent" },
			{ toast: null, sound: null },
			{ toast: toast(1, 2, "urgent", "app.orders"), sound: null },
			{ toast: null, sound: null },
		],
	],
];

for (const [name, steps, expected] of BURSTS) {
	test(`coalescing: ${name}`, () => {
		assert.deepEqual(run(steps), expected);
	});
}

test("the coalescing window is the one given", () => {
	const steps = [
		[0, [normal("app.tasks")]],
		[2500, [urgent("app.orders")]],
	];
	const sounds = (windowMs) => {
		let burst = null;
		return steps.map(([now, alerts]) => {
			const result = coalesce(burst, alerts, now, windowMs);
			burst = result.burst;
			return [result.toast.id, result.sound];
		});
	};

	assert.deepEqual(sounds(2000), [
		[1, "standard"],
		[2, "urgent"],
	]);
	assert.deepEqual(sounds(3000), [
		[1, "standard"],
		[1, "urgent"],
	]);
});
