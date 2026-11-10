// The items of a window tab, page by page: one source, or the "All" tab merging every action source
// [FR-UI-02]. No DOM and no frappe, so the merging and paging can be tested with node --test.

const PRIORITY_RANK = { immediate: 0, urgent: 1, normal: 2 };

// The server's order within a source [FR-API-02]: overdue first, then immediate, urgent, normal, then newest.
// Dates are compared as text: the server sends them all as ISO text in the system time zone, which sorts
// like the dates themselves, and an item without a date comes last in its class.
export function compareItems(a, b) {
	if (a.overdue !== b.overdue) return a.overdue ? -1 : 1;
	const rank = (PRIORITY_RANK[a.priority] ?? 2) - (PRIORITY_RANK[b.priority] ?? 2);
	if (rank) return rank;
	if (a.date === b.date) return 0;
	if (!a.date || !b.date) return a.date ? -1 : 1;
	return a.date > b.date ? -1 : 1;
}

// One page of the merged streams, or the streams that must be fetched further before it can be told.
// A stream is {key, items, done}: the items fetched so far in the source's own order, and whether the
// source has no more. Streams are merged like sorted lists, so each keeps its own order; on a tie the
// earlier stream goes first. Returns {need: [keys]} or {need: [], items: [{source, item}], hasMore}.
export function mergePage(streams, page, size) {
	const end = (page + 1) * size;
	const heads = streams.map(() => 0);
	const merged = [];
	while (merged.length < end) {
		// A stream whose fetched items are used up may still hold the next item.
		const need = streams.filter(
			(stream, i) => heads[i] === stream.items.length && !stream.done
		);
		if (need.length) return { need: need.map((stream) => stream.key) };

		let next = -1;
		streams.forEach((stream, i) => {
			const item = stream.items[heads[i]];
			if (item && (next < 0 || compareItems(item, streams[next].items[heads[next]]) < 0))
				next = i;
		});
		if (next < 0) break;
		merged.push({ source: streams[next].key, item: streams[next].items[heads[next]++] });
	}

	const fetched = streams.reduce((total, stream) => total + stream.items.length, 0);
	return {
		need: [],
		items: merged.slice(page * size),
		hasMore: fetched > end || streams.some((stream) => !stream.done),
	};
}

// The pages of a tab. `fetchItems(key, start, size)` answers like the get_items endpoint: {state, items,
// has_more}. A source that fails (an error state or a failed request) counts as having no more items and is
// listed in `failed`, so the other sources of the "All" tab still show; `retry()` asks them again.
export function createFeed(keys, fetchItems, size) {
	const streams = keys.map((key) => ({
		key,
		items: [],
		ids: new Set(),
		offset: 0,
		done: false,
		failed: false,
		pending: null,
	}));

	async function load(stream) {
		let answer;
		try {
			answer = await fetchItems(stream.key, stream.offset, size);
		} catch {
			answer = null;
		}
		if (answer?.state !== "ok") {
			stream.failed = stream.done = true;
			return;
		}
		stream.offset += answer.items.length;
		// An item pushed onto the next page by a change in the source meanwhile is shown once.
		const fresh = answer.items.filter((item) => !stream.ids.has(item.id));
		for (const item of fresh) stream.ids.add(item.id);
		stream.items.push(...fresh);
		stream.done = !answer.has_more || !answer.items.length;
	}

	// Pages asked for at the same time share the request for a stream instead of fetching one offset twice.
	function fill(stream) {
		stream.pending ??= load(stream).finally(() => {
			stream.pending = null;
		});
		return stream.pending;
	}

	return {
		async page(number) {
			for (;;) {
				const result = mergePage(streams, number, size);
				if (!result.need.length) {
					const failed = streams
						.filter((stream) => stream.failed)
						.map((stream) => stream.key);
					return { items: result.items, hasMore: result.hasMore, failed };
				}
				await Promise.all(
					result.need.map((key) => fill(streams.find((stream) => stream.key === key)))
				);
			}
		},
		retry() {
			for (const stream of streams) {
				if (stream.failed) stream.failed = stream.done = false;
			}
		},
	};
}
