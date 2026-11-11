const PREFIX = "attention_center.api.";

// Sends a whitelisted method to the server with `fetch`, not `frappe.call`: `frappe.call` opens a core dialog
// and plays the error sound on a 403, 404 or 5xx answer even with `silent: true`, and these requests run in
// the background (§7.1). Any answer other than 2xx rejects. `csrfToken()` is read for every request.
export function createTransport(fetch, csrfToken) {
	return async function call(method, args) {
		const response = await fetch(`/api/method/${method}`, {
			method: "POST",
			credentials: "same-origin",
			headers: {
				Accept: "application/json",
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": csrfToken(),
			},
			body: JSON.stringify(args),
		});
		if (!response.ok) throw new Error(`${method} answered HTTP ${response.status}`);
		return (await response.json()).message;
	};
}

// The server endpoints the client uses (§5). `call(method, args)` returns a promise of the method's result.
export function createApi(call) {
	const reads = new Map();
	let writes = Promise.resolve();

	// A read already on its way is shared instead of sent again.
	function read(method, args = {}) {
		const key = method + JSON.stringify(args);
		if (!reads.has(key)) {
			reads.set(
				key,
				call(PREFIX + method, args).finally(() => reads.delete(key))
			);
		}
		return reads.get(key);
	}

	// Writes are sent one after the other, so the server keeps the user's last change.
	function write(method, args) {
		const result = writes.then(() => call(PREFIX + method, args));
		writes = result.catch(() => {});
		return result;
	}

	return {
		getSummary: () => read("get_summary"),
		getItems: (source, start, pageLength) =>
			read("get_items", { source, start, page_length: pageLength }),
		markSeen: (source) => write("mark_seen", { source }),
		setPreferences: (prefs) => write("set_preferences", { prefs }),
		noteAutoOpened: () => write("note_auto_opened", {}),
	};
}
