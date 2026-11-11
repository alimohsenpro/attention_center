// Cross-tab coordination of the alert sounds [FR-SND-04, §7.5]: of the browser's tabs that want to play the same
// alert, exactly one does. BroadcastChannel and localStorage only: the Web Locks API needs a secure context, and
// the production origin is plain HTTP (T-06).

export const CHANNEL_NAME = "attention_center";
const CLAIM_PREFIX = "attention_center:claim:";
// A hidden tab claims an alert only after this delay plus a random part of HIDDEN_JITTER_MS, so that a visible tab,
// which claims at once, wins, and two hidden tabs seldom claim at the same moment.
const HIDDEN_DELAY_MS = 120;
const HIDDEN_JITTER_MS = 80;
// A tab plays once its claim has stood this long: a claim another tab wrote at the same moment reaches it by then,
// and the later of the two stands in every tab.
const SETTLE_MS = 120;
// Every tab has fetched a change well within this time (a broadcast's random wait, the debounce, the request);
// older claims are forgotten and removed from the storage.
const CLAIM_TTL_MS = 30000;

const SYSTEM_CLOCK = {
	now: () => Date.now(),
	setTimeout: (callback, ms) => setTimeout(callback, ms),
};

// `channel` is BroadcastChannel(CHANNEL_NAME), `storage` localStorage, `page` the document (visibilityState);
// `safe` wraps every handler and timer in the client's guard.
export function createTabs({
	channel,
	storage,
	page,
	safe,
	clock = SYSTEM_CLOCK,
	random = Math.random,
	tab = newTabId(),
}) {
	// The claims other tabs announced on the channel, by claim key (claimKey), with the time they were heard: the
	// message may arrive before the claim's write to the storage does.
	const heard = new Map();
	channel.addEventListener(
		"message",
		safe(({ data }) => {
			if (data?.claim) heard.set(data.claim, clock.now());
		})
	);

	const live = (at) => clock.now() - at < CLAIM_TTL_MS;

	function stored(key) {
		const claim = JSON.parse(storage.getItem(CLAIM_PREFIX + key));
		return claim && live(claim.at) ? claim : null;
	}

	function claimed(key) {
		return (heard.has(key) && live(heard.get(key))) || Boolean(stored(key));
	}

	function write(key) {
		forgetOld();
		storage.setItem(CLAIM_PREFIX + key, JSON.stringify({ tab, at: clock.now() }));
		channel.postMessage({ claim: key });
	}

	function forgetOld() {
		for (const [key, at] of heard) if (!live(at)) heard.delete(key);
		const names = Array.from({ length: storage.length }, (_, index) => storage.key(index));
		for (const name of names) {
			if (name.startsWith(CLAIM_PREFIX) && !stored(name.slice(CLAIM_PREFIX.length))) {
				storage.removeItem(name);
			}
		}
	}

	// Resolves true in the one tab that plays alert `id`, false in the others. A tab that finds the alert claimed
	// (by another tab, or by itself earlier) leaves it; otherwise it claims it, at once when visible, after a
	// short random delay when hidden, and plays only if its claim still stands once competing claims had time to
	// land.
	function claim(id) {
		const key = claimKey(id);
		return new Promise((resolve) => {
			if (claimed(key)) {
				resolve(false);
				return;
			}
			const delay =
				page.visibilityState === "visible"
					? 0
					: HIDDEN_DELAY_MS + random() * HIDDEN_JITTER_MS;
			clock.setTimeout(
				safe(() => {
					if (claimed(key)) {
						resolve(false);
						return;
					}
					write(key);
					clock.setTimeout(
						safe(() => resolve(stored(key)?.tab === tab)),
						SETTLE_MS
					);
				}),
				delay
			);
		});
	}

	// Records alert `id` as handled without playing it: this tab's burst already sounded for it
	// (alerts/coalesce.js), so a tab that fetches the same change later stays silent as well.
	function mark(id) {
		const key = claimKey(id);
		if (!claimed(key)) write(key);
	}

	return { claim, mark };
}

// The id under which the tabs claim the sound of one summary's alerts: each source that sounded, with its count
// and latest date as the server sent them. Tabs that fetched the same change at different moments (a broadcast's
// random wait, §6) agree on it, where a bucket of the clock would split them at its edge. Empty when no alert
// sounds.
export function alertId(alerts, summary) {
	const sources = new Map(summary.sources.map((source) => [source.key, source]));
	return alerts
		.filter((alert) => alert.sound)
		.map(({ source }) => {
			const { count, latest } = sources.get(source);
			return `${source}#${count}@${latest ?? ""}`;
		})
		.sort()
		.join(" ");
}

// The key under which the tabs claim alert `id`: its FNV-1a hash, so that the storage, which outlives the
// session and may be read by the next user of the browser, names no source and no count. A collision among the
// few claims alive at once is negligible.
function claimKey(id) {
	let hash = 0x811c9dc5;
	for (let index = 0; index < id.length; index++) {
		hash = Math.imul(hash ^ id.charCodeAt(index), 0x01000193);
	}
	return (hash >>> 0).toString(36);
}

// crypto.randomUUID needs a secure context; the id only has to differ between the tabs of one browser.
function newTabId() {
	return Math.random().toString(36).slice(2);
}
