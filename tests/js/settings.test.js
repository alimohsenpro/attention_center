import assert from "node:assert/strict";
import test from "node:test";

import { createPreferenceEditor } from "../../attention_center/public/js/attention_center/util/settings.js";
import { settle } from "./fakes.js";

const PREFS = {
	display_mode: "Dialog",
	auto_open_on_login: true,
	sound_scope: "Action Items",
	tone: "chime",
	volume: 60,
	dnd_until: null,
	launcher_collapsed: false,
};

// An editor on a store holding `prefs`, whose writes wait until the test answers them, in the order they were sent.
function editorFor(prefs = PREFS) {
	let current = prefs;
	const writes = [];
	const statuses = [];
	const editor = createPreferenceEditor({
		getPrefs: () => current,
		setPrefs: (next) => (current = next),
		write: (changes) =>
			new Promise((resolve, reject) => writes.push({ changes, resolve, reject })),
		onStatus: (status) => statuses.push(status),
	});
	return {
		editor,
		statuses,
		prefs: () => current,
		sent: () => writes.map((write) => write.changes),
		// Answers the oldest write not answered yet.
		async answer(ok) {
			const write = writes.find((candidate) => !candidate.answered);
			write.answered = true;
			if (ok) write.resolve(current);
			else write.reject(new Error("set_preferences answered HTTP 500"));
			await settle();
		},
	};
}

test("a change applies at once, before the server answers, and is sent", () => {
	const { editor, prefs, sent, statuses } = editorFor();

	editor.change({ tone: "drop" });

	assert.deepEqual(prefs(), { ...PREFS, tone: "drop" });
	assert.deepEqual(sent(), [{ tone: "drop" }]);
	assert.deepEqual(statuses, ["saving"]);
});

test("the status turns to saved once the server stored the change", async () => {
	const { editor, statuses, answer } = editorFor();

	editor.change({ volume: 35 });
	await answer(true);

	assert.deepEqual(statuses, ["saving", "saved"]);
});

// [change, what set_preferences receives].
const VALUE_CASES = [
	[{ sound_scope: "Everything" }, { sound_scope: "Everything" }],
	[{ tone: "telegraph" }, { tone: "telegraph" }],
	[{ volume: 0 }, { volume: 0 }],
	[{ dnd_until: "2026-11-11 10:00:00" }, { dnd_until: "2026-11-11 10:00:00" }],
	[{ auto_open_on_login: false }, { auto_open_on_login: "No" }],
	[{ display_mode: "Drawer" }, { display_mode: "Drawer" }],
];

for (const [change, expected] of VALUE_CASES) {
	test(`${JSON.stringify(change)} is sent as ${JSON.stringify(expected)}`, () => {
		const { editor, sent } = editorFor();

		editor.change(change);

		assert.deepEqual(sent(), [expected]);
	});
}

test("turning auto-open on and Do Not Disturb off send Yes and null", () => {
	const { editor, sent } = editorFor({
		...PREFS,
		auto_open_on_login: false,
		dnd_until: "2026-11-11T10:00:00",
	});

	editor.change({ auto_open_on_login: true, dnd_until: null });

	assert.deepEqual(sent(), [{ auto_open_on_login: "Yes", dnd_until: null }]);
});

test("a value equal to the current one is neither applied again nor sent", () => {
	const { editor, prefs, sent, statuses } = editorFor();

	editor.change({ tone: PREFS.tone, display_mode: PREFS.display_mode });

	assert.equal(prefs(), PREFS);
	assert.deepEqual(sent(), []);
	assert.deepEqual(statuses, []);
});

test("only the values that differ are sent", () => {
	const { editor, sent } = editorFor();

	editor.change({ tone: PREFS.tone, volume: 80 });

	assert.deepEqual(sent(), [{ volume: 80 }]);
});

test("a change the server did not store keeps applying and is reported", async () => {
	const { editor, prefs, statuses, answer } = editorFor();

	editor.change({ tone: "drop" });
	await answer(false);

	assert.equal(prefs().tone, "drop");
	assert.deepEqual(statuses, ["saving", "failed"]);
});

test("the status stays saving until the last write is answered", async () => {
	const { editor, statuses, answer } = editorFor();

	editor.change({ volume: 30 });
	editor.change({ volume: 40 });
	await answer(true);
	assert.deepEqual(statuses, ["saving"]);

	await answer(true);
	assert.deepEqual(statuses, ["saving", "saved"]);
});

test("a later write of the same preference that succeeds clears its failure", async () => {
	const { editor, statuses, answer } = editorFor();

	editor.change({ volume: 30 });
	editor.change({ volume: 40 });
	await answer(false);
	await answer(true);

	assert.deepEqual(statuses, ["saving", "saved"]);
});

test("a failure stays reported while another preference is stored", async () => {
	const { editor, statuses, answer } = editorFor();

	editor.change({ tone: "drop" });
	await answer(false);
	editor.change({ volume: 30 });
	await answer(true);

	assert.deepEqual(statuses, ["saving", "failed", "saving", "failed"]);
});

test("trying again sends the preferences that failed, with their current values", async () => {
	const { editor, sent, statuses, answer } = editorFor();

	editor.change({ volume: 30 });
	editor.change({ volume: 40, tone: "knock" });
	await answer(false);
	await answer(false);
	editor.retry();
	await answer(true);

	assert.deepEqual(sent().at(-1), { volume: 40, tone: "knock" });
	assert.deepEqual(statuses, ["saving", "failed", "saving", "saved"]);
});

test("trying again with nothing failed sends nothing", async () => {
	const { editor, sent, answer } = editorFor();

	editor.change({ volume: 30 });
	await answer(true);
	editor.retry();

	assert.equal(sent().length, 1);
});
