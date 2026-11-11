// How a change made in the window's settings view applies and is stored [FR-SND-02, FR-SET-02, FR-UI-03]. No DOM and
// no frappe, so it can be tested with node --test.

// The sound scopes, named as in the sound_scope preference (§5).
export const SOUND_SCOPES = ["Urgent Only", "Action Items", "Everything"];

// Applies the user's changes to the effective preferences at once and stores them on the server.
//
// `getPrefs()` and `setPrefs(prefs)` read and replace the preferences in the store; `write(changes)` sends changes to
// set_preferences and returns a promise (api.setPreferences, which sends one write after the other); `onStatus(status)`
// hears each new state of the writes: "saving" while one is on its way, then "saved", or "failed" while a change the
// server did not store is left. A change that failed keeps applying in this page load, and `retry()` sends the
// preferences that failed again, with their current values.
export function createPreferenceEditor({ getPrefs, setPrefs, write, onStatus }) {
	let status = "idle";
	let writing = 0;
	// The preferences whose last write failed. Writes settle in the order they were sent, so the last one decides.
	const failed = new Set();

	function report() {
		const next = writing ? "saving" : failed.size ? "failed" : "saved";
		if (next === status) return;
		status = next;
		onStatus(status);
	}

	function send(fields) {
		const prefs = getPrefs();
		writing++;
		report();
		return write(
			Object.fromEntries(fields.map((field) => [field, serverValue(field, prefs[field])]))
		)
			.then(
				() => fields.forEach((field) => failed.delete(field)),
				() => fields.forEach((field) => failed.add(field))
			)
			.finally(() => {
				writing--;
				report();
			});
	}

	return {
		// Applies `changes` ({preference: value}, valued as in the effective preferences) and stores the values that
		// differ from the current ones.
		change(changes) {
			const prefs = getPrefs();
			const fields = Object.keys(changes).filter((field) => changes[field] !== prefs[field]);
			if (!fields.length) return Promise.resolve();
			setPrefs({ ...prefs, ...changes });
			return send(fields);
		},
		retry() {
			return failed.size ? send([...failed]) : Promise.resolve();
		},
	};
}

// set_preferences takes auto-open as "Yes" or "No", where the effective preferences hold a boolean (§5).
function serverValue(field, value) {
	if (field === "auto_open_on_login") return value ? "Yes" : "No";
	return value;
}
