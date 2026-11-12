import assert from "node:assert/strict";
import test from "node:test";

import {
	dndChoice,
	dndUntil,
	fromInputValue,
	msUntil,
	remindAt,
	toInputValue,
} from "../../attention_center/public/js/attention_center/util/time.js";

const NOW = "2026-11-11 09:00:00";

// [choice, now, when Do Not Disturb ends].
const UNTIL_CASES = [
	["hour", NOW, "2026-11-11 10:00:00"],
	["hour", "2026-11-11 23:30:00", "2026-11-12 00:30:00"],
	["hour", "2026-12-31 23:15:00", "2027-01-01 00:15:00"],
	["hour", "2026-11-11T09:00:00", "2026-11-11 10:00:00"],
	["day", NOW, "2026-11-12 00:00:00"],
	["day", "2026-11-11 00:00:00", "2026-11-12 00:00:00"],
	["day", "2026-11-11 23:59:59", "2026-11-12 00:00:00"],
	["day", "2026-11-30 18:00:00", "2026-12-01 00:00:00"],
	["day", "2028-02-28 12:00:00", "2028-02-29 00:00:00"],
	["day", "2026-12-31 08:00:00", "2027-01-01 00:00:00"],
	["off", NOW, null],
];

for (const [choice, now, expected] of UNTIL_CASES) {
	test(`Do Not Disturb "${choice}" chosen at ${now} ends at ${expected}`, () => {
		assert.equal(dndUntil(choice, now), expected);
	});
}

test("the browser's own time zone does not move the end of Do Not Disturb", () => {
	const zone = process.env.TZ;
	try {
		// The night the clocks go back in this zone.
		process.env.TZ = "America/New_York";
		assert.equal(dndUntil("hour", "2026-11-01 01:30:00"), "2026-11-01 02:30:00");
		assert.equal(dndUntil("day", "2026-10-31 12:00:00"), "2026-11-01 00:00:00");
	} finally {
		if (zone === undefined) delete process.env.TZ;
		else process.env.TZ = zone;
	}
});

// [when Do Not Disturb ends, the choice the settings view shows at NOW].
const CHOICE_CASES = [
	[null, "off"],
	["", "off"],
	["2026-11-11 08:59:59", "off"],
	[NOW, "off"],
	["2026-11-11 09:00:01", "hour"],
	["2026-11-11 10:00:00", "hour"],
	["2026-11-11T10:00:00", "hour"],
	["2026-11-12 00:00:00", "day"],
	["2026-11-12T00:00:00", "day"],
	["2026-11-13 00:00:00", "hour"],
];

for (const [until, expected] of CHOICE_CASES) {
	test(`a Do Not Disturb ending at ${JSON.stringify(until)} shows as "${expected}"`, () => {
		assert.equal(dndChoice(until, NOW), expected);
	});
}

for (const choice of ["off", "hour", "day"]) {
	test(`the choice "${choice}" shows as itself right after it is made`, () => {
		assert.equal(dndChoice(dndUntil(choice, NOW), NOW), choice);
	});
}

test("an hour of Do Not Disturb that started at 23:30 is not taken for the end of the day", () => {
	const now = "2026-11-11 23:30:00";

	assert.equal(dndChoice(dndUntil("hour", now), now), "hour");
});

test("the time left until the end is counted in milliseconds", () => {
	assert.equal(msUntil("2026-11-11 10:00:00", NOW), 3600 * 1000);
	assert.equal(msUntil("2026-11-12T00:00:00", "2026-11-11 23:59:59"), 1000);
});

// [choice, now, when the reminder falls due].
const REMIND_CASES = [
	["hour", NOW, "2026-11-11 10:00:00"],
	["hour", "2026-11-11 23:30:00", "2026-11-12 00:30:00"],
	["hour", "2026-11-11T09:00:00", "2026-11-11 10:00:00"],
	["morning", NOW, "2026-11-12 09:00:00"],
	["morning", "2026-11-11 00:30:00", "2026-11-12 09:00:00"],
	["morning", "2026-11-11 23:59:59", "2026-11-12 09:00:00"],
	["morning", "2026-11-30 18:00:00", "2026-12-01 09:00:00"],
	["morning", "2028-02-28 12:00:00", "2028-02-29 09:00:00"],
	["morning", "2026-12-31 17:00:00", "2027-01-01 09:00:00"],
];

for (const [choice, now, expected] of REMIND_CASES) {
	test(`a reminder "${choice}" chosen at ${now} falls due at ${expected}`, () => {
		assert.equal(remindAt(choice, now), expected);
	});
}

test("the browser's own time zone does not move a reminder", () => {
	const zone = process.env.TZ;
	try {
		process.env.TZ = "America/New_York";
		assert.equal(remindAt("hour", "2026-11-01 01:30:00"), "2026-11-01 02:30:00");
		assert.equal(remindAt("morning", "2026-10-31 20:00:00"), "2026-11-01 09:00:00");
	} finally {
		if (zone === undefined) delete process.env.TZ;
		else process.env.TZ = zone;
	}
});

// [value of a datetime-local input, the time it stands for].
const INPUT_CASES = [
	["2026-11-12T14:30", "2026-11-12 14:30:00"],
	["2026-11-12T14:30:15", "2026-11-12 14:30:15"],
	["", null],
	["2026-11-12", null],
	["2026-11-12T14", null],
	["tomorrow", null],
];

for (const [value, expected] of INPUT_CASES) {
	test(`the input value ${JSON.stringify(value)} stands for ${expected}`, () => {
		assert.equal(fromInputValue(value), expected);
	});
}

test("a time becomes the value of a datetime-local input to the minute", () => {
	assert.equal(toInputValue("2026-11-12 14:30:15"), "2026-11-12T14:30");
	assert.equal(fromInputValue(toInputValue(NOW)), NOW);
});
