// Keeps the preferences of the user's tabs in step: a change made in one tab (the settings view, the mode button, the
// launcher's collapse) applies in the others at once, so that Do Not Disturb set in one tab silences every tab
// [FR-SND-02]. BroadcastChannel only (T-06). A message holds only the preferences that changed, so that a tab with
// older values for the others (changed in another browser, or a write that failed in that tab) does not overwrite
// them in the tabs that have newer ones. A message names its user, and a tab of another user, left open in the same
// browser, ignores it.
//
// `store` holds the preferences; `channel` is BroadcastChannel(CHANNEL_NAME); `safe` wraps the handlers in the
// client's guard.
export function sharePreferences({ store, channel, user, safe }) {
	// The preferences last received, which are not sent back.
	let received = null;
	channel.addEventListener(
		"message",
		safe(({ data }) => {
			if (!data?.changes || data.user !== user) return;
			received = { ...store.get().prefs, ...data.changes };
			store.set({ prefs: received });
		})
	);
	store.subscribe(
		safe((state, previous) => {
			if (state.prefs === previous.prefs || state.prefs === received) return;
			const changes = changed(previous.prefs, state.prefs);
			if (Object.keys(changes).length) channel.postMessage({ changes, user });
		})
	);
}

function changed(before, after) {
	return Object.fromEntries(
		Object.entries(after).filter(([field, value]) => before[field] !== value)
	);
}
