// The window opens by itself once per login session when action items wait [FR-ALERT-05, §7.4]. Pure: it reads
// the store and is handed the boot's session marker, so it can be tested without a browser.

// The store.onSummary listener that decides on the first summary of the page load, and on no later one: a window
// opening while the user works would take their keystrokes (D-03). It opens the window when the login session
// has not had its auto-open yet (`shouldAutoOpen`, from the boot), the effective auto_open_on_login preference is
// on and action items wait. `open(newSince)` opens it on "All" with the "new since you last looked" line and
// resolves whether it opened; `onOpened()` then records the auto-open for the session (note_auto_opened). A window
// the user opened before the first summary is left as it is and counts as opened: they are looking already.
export function autoOpenOnLogin({ shouldAutoOpen, store, open, onOpened }) {
	return ({ previous, summary }) => {
		const { prefs, ui } = store.get();
		if (previous || !shouldAutoOpen || !prefs.auto_open_on_login || !summary.totals.action) {
			return undefined;
		}
		if (ui.open) {
			onOpened();
			return undefined;
		}
		return open(newSinceLastLooked(summary)).then((opened) => {
			if (opened) onOpened();
		});
	};
}

// How many action items arrived since the user last looked at their sources. Read from the summary before the
// window opens: opening it on "All" marks every action source seen, after which new_since reads 0.
export function newSinceLastLooked(summary) {
	return summary.sources
		.filter((source) => source.kind === "action")
		.reduce((total, source) => total + source.new_since, 0);
}
