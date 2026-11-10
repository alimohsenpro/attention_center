export const NUDGE_EVENT = "attention_center_nudge";
// A burst of triggers is sent as one request once this long passes without another,
const DEBOUNCE_MS = 1500;
// or this long after its first trigger, so that a steady stream of nudges still refreshes.
const MAX_WAIT_MS = 5000;
// A broadcast reaches every desk user at once; each waits a random part of this before refreshing (§6).
const BROADCAST_JITTER_MS = 5000;

const SYSTEM_CLOCK = {
	now: () => Date.now(),
	setTimeout: (callback, ms) => setTimeout(callback, ms),
	clearTimeout: (id) => clearTimeout(id),
};

// The refresh loop [FR-RT-02, §7.3]: calls `refresh(actor)` (store.refreshSummary) once after the start, then on
// nudges, when the page becomes visible, when the socket connects again, when the browser is back online, and
// every `heartbeatSeconds` while the page is visible. Realtime only speeds it up: a hidden tab still follows
// nudges, so that its alerts can play, but it does not poll.
//
// `realtime` is frappe.realtime (on), `page` the document (visibilityState, visibilitychange), `network` the
// window (online); `safe` wraps every handler and timer in the client's guard.
export function startRefreshLoop({
	refresh,
	heartbeatSeconds,
	realtime,
	page,
	network,
	safe,
	clock = SYSTEM_CLOCK,
	random = Math.random,
}) {
	let debounce = null;
	let burstStart = 0;
	let burstActor = null;
	let jitter = null;
	let heartbeat = null;

	// The trigger joins the pending burst. A nudge names its actor; any other trigger has none.
	function trigger(actor = null) {
		const now = clock.now();
		if (debounce === null) {
			burstStart = now;
			burstActor = actor;
		} else {
			clock.clearTimeout(debounce);
			if (burstActor !== actor) burstActor = null;
		}
		debounce = clock.setTimeout(
			safe(send),
			Math.min(DEBOUNCE_MS, burstStart + MAX_WAIT_MS - now)
		);
	}

	function send() {
		debounce = null;
		return refresh(burstActor);
	}

	function onNudge({ broadcast, actor }) {
		if (!broadcast) {
			trigger(actor);
		} else if (jitter === null) {
			// The refresh after the pending wait covers every broadcast received before it.
			jitter = clock.setTimeout(
				safe(() => {
					jitter = null;
					trigger();
				}),
				random() * BROADCAST_JITTER_MS
			);
		}
	}

	function armHeartbeat() {
		clock.clearTimeout(heartbeat);
		heartbeat =
			page.visibilityState === "visible"
				? clock.setTimeout(safe(beat), heartbeatSeconds * 1000)
				: null;
	}

	function beat() {
		armHeartbeat();
		trigger();
	}

	function onVisibilityChange() {
		armHeartbeat();
		if (page.visibilityState === "visible") trigger();
	}

	realtime.on(NUDGE_EVENT, safe(onNudge));
	// socket.io 4 emits connect on the socket after every reconnection too; its reconnect event belongs to the
	// socket's manager, which frappe.realtime.on does not reach.
	realtime.on(
		"connect",
		safe(() => trigger())
	);
	page.addEventListener("visibilitychange", safe(onVisibilityChange));
	network.addEventListener(
		"online",
		safe(() => trigger())
	);
	trigger();
	armHeartbeat();
}
