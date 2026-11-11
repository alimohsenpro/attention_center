// Keeps the preferences of the user's tabs in step: a change made in one tab (the settings view, the mode button, the
// launcher's collapse) applies in the others at once, so that Do Not Disturb set in one tab silences every tab
// [FR-SND-02]. BroadcastChannel only (T-06). A message names its user, and a tab of another user, left open in the
// same browser, ignores it.
//
// `store` holds the preferences; `channel` is BroadcastChannel(CHANNEL_NAME); `safe` wraps the handlers in the
// client's guard.
export function sharePreferences({ store, channel, user, safe }) {
	// The preferences last received, which are not sent back.
	let received = null;
	channel.addEventListener(
		"message",
		safe(({ data }) => {
			if (!data?.prefs || data.user !== user) return;
			received = data.prefs;
			store.set({ prefs: data.prefs });
		})
	);
	store.subscribe(
		safe((state, previous) => {
			if (state.prefs !== previous.prefs && state.prefs !== received) {
				channel.postMessage({ prefs: state.prefs, user });
			}
		})
	);
}
