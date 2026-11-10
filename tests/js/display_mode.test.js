import assert from "node:assert/strict";
import test from "node:test";

import {
	displayMode,
	nextDisplayMode,
} from "../../attention_center/public/js/attention_center/util/display_mode.js";

// [effective display_mode preference, mode of the window, mode the mode button switches to]
const CASES = [
	["Dialog", "Dialog", "Panel"],
	["Panel", "Panel", "Drawer"],
	["Drawer", "Drawer", "Dialog"],
	["", "Dialog", "Panel"],
	[undefined, "Dialog", "Panel"],
	["Default", "Dialog", "Panel"],
	["panel", "Dialog", "Panel"],
];

for (const [preference, mode, next] of CASES) {
	test(`display_mode ${JSON.stringify(preference)} shows the window as ${mode}, the button switches to ${next}`, () => {
		assert.equal(displayMode(preference), mode);
		assert.equal(nextDisplayMode(preference), next);
	});
}

test("the mode button goes through the three modes and back", () => {
	const visited = ["Dialog"];
	for (let i = 0; i < 3; i++) visited.push(nextDisplayMode(visited.at(-1)));
	assert.deepEqual(visited, ["Dialog", "Panel", "Drawer", "Dialog"]);
});
