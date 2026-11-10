// Every entry point of the client runs through one guard: the first failure is logged, undoes what the client
// added to the page and turns it off for the rest of the page load, so the desk keeps working [NFR-REL-01].
export function createGuard() {
	let failed = false;
	const cleanups = [];

	function report(error) {
		console.error("[attention_center]", error);
	}

	function fail(error) {
		report(error);
		if (failed) return;
		failed = true;
		for (const cleanup of cleanups.splice(0)) {
			try {
				cleanup();
			} catch (cleanupError) {
				report(cleanupError);
			}
		}
	}

	function run(fn, ...args) {
		if (failed) return undefined;
		try {
			const result = fn(...args);
			// An async handler fails later, through its promise.
			return typeof result?.then === "function" ? Promise.resolve(result).catch(fail) : result;
		} catch (error) {
			fail(error);
			return undefined;
		}
	}

	return {
		run,
		safe:
			(fn) =>
			(...args) =>
				run(fn, ...args),
		addCleanup: (cleanup) => cleanups.push(cleanup),
	};
}
