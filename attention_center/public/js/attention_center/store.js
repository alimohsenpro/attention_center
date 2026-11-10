// The client's state, {summary, prefs, ui}. Listeners receive the new and the previous state after each change.
export function createStore(initial) {
	let state = { ...initial };
	const listeners = new Set();

	return {
		get: () => state,
		set(changes) {
			const previous = state;
			state = { ...state, ...changes };
			for (const listener of [...listeners]) listener(state, previous);
		},
		subscribe(listener) {
			listeners.add(listener);
			return () => listeners.delete(listener);
		},
	};
}
