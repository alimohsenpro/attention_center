// The client's state, {summary, prefs, ui}. Listeners receive the new and the previous state after each change.
// `getSummary()` asks the server for the summary (api.getSummary); refreshSummary stores its answer.
export function createStore(initial, getSummary) {
	let state = initial;
	const listeners = new Set();
	const summaryListeners = new Set();
	// The summary request on its way, and the one asked for while it was.
	let running = null;
	let queued = null;

	function set(changes) {
		const previous = state;
		state = { ...state, ...changes };
		for (const listener of listeners) listener(state, previous);
	}

	function listen(registry, listener) {
		registry.add(listener);
		return () => registry.delete(listener);
	}

	async function fetchSummary(actor) {
		let summary;
		try {
			summary = await getSummary();
		} catch {
			// A failed request is not a failure of the client: the launcher keeps what it shows.
			return;
		}
		const previous = state.summary;
		set({ summary });
		for (const listener of summaryListeners) listener({ previous, summary, actor });
	}

	// Fetches the summary into the state; the promise settles once it is stored or its request failed. One
	// request at a time: a call while one is on its way sends no second one but asks for one more after it,
	// since the change that prompted the call may have been committed after the server read the counts.
	// The calls made meanwhile share that follow-up.
	//
	// `actor` is the user a nudge names as the author of the change, or null when the cause is unknown. Calls
	// served by one request keep their actor only if they all name the same one.
	function refreshSummary(actor = null) {
		if (!running) {
			running = fetchSummary(actor).finally(() => (running = null));
			return running;
		}
		if (queued) {
			if (queued.actor !== actor) queued.actor = null;
		} else {
			const followUp = { actor };
			const send = () => {
				queued = null;
				return refreshSummary(followUp.actor);
			};
			followUp.promise = running.then(send);
			queued = followUp;
		}
		return queued.promise;
	}

	return {
		get: () => state,
		set,
		subscribe: (listener) => listen(listeners, listener),
		// What the alert layer compares (§7.4): `listener({previous, summary, actor})` after each summary is
		// stored, `previous` being null for the first one of the page load.
		onSummary: (listener) => listen(summaryListeners, listener),
		refreshSummary,
	};
}
