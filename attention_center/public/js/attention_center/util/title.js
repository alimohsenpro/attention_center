// The browser tab title starts with "(N) " while N action items exist [FR-UI-06].

// `applied` is the prefix this module wrote last: only that is removed, so a page title that happens to
// start with a number in brackets is left alone.
export function retitle(title, applied, count) {
	const bare = applied && title.startsWith(applied) ? title.slice(applied.length) : title;
	const prefix = count ? `(${count}) ` : "";
	return { title: prefix + bare, applied: prefix };
}

// Frappe rewrites the title on every navigation; watching <title> puts the counter back each time.
export function watchTitle(doc, Observer) {
	let applied = "";
	let count = "";

	function apply() {
		const next = retitle(doc.title, applied, count);
		applied = next.applied;
		if (next.title !== doc.title) doc.title = next.title;
	}

	const observer = new Observer(apply);
	observer.observe(doc.querySelector("title"), {
		childList: true,
		characterData: true,
		subtree: true,
	});

	return {
		set(value) {
			count = value;
			apply();
		},
		stop() {
			observer.disconnect();
			count = "";
			apply();
		},
	};
}
