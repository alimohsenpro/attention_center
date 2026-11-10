import { LEVELS } from "./policy.js";

// The tone roles of new items from least to most pressing.
const SOUNDS = ["standard", "urgent", "immediate"];

// Merges the alerts of a burst into one toast and one sound [FR-ALERT-03]. Pure: the caller keeps the returned
// `burst` and hands it back with the alerts of the next summary (newItemAlerts) and the time in milliseconds.
//
// A burst starts with the first alert that shows a toast or plays a sound, and takes every alert of the next
// `windowMs`. Its first alert is shown and heard at once, so an urgent item never waits for the window to end;
// later alerts update the same toast ("N new items", the highest level so far) and play a sound only when it is
// more pressing than the one the burst already played. A burst of equal or lower alerts therefore sounds once,
// and the last sound it plays is always that of its highest level.
//
// Returns {burst, toast, sound}: `toast` is null or {id, count, level, sticky, source} for the toast to show,
// or to update when one with that id is still shown; `source` is the key of the burst's only source, or null
// when its items come from several. `sound` is null or the tone role to play.
export function coalesce(burst, alerts, now, windowMs) {
	const toasted = alerts.filter((alert) => alert.toast);
	const sound = highest(
		SOUNDS,
		alerts.map((alert) => alert.sound)
	);
	if (!toasted.length && !sound) return { burst, toast: null, sound: null };

	const current =
		burst && now - burst.startedAt < windowMs
			? burst
			: {
					id: (burst?.id ?? 0) + 1,
					startedAt: now,
					count: 0,
					level: null,
					sticky: false,
					sources: [],
					sounded: null,
			  };
	const next = {
		...current,
		count: toasted.reduce((total, alert) => total + alert.count, current.count),
		level: highest(LEVELS, [current.level, ...toasted.map((alert) => alert.level)]),
		sticky: current.sticky || toasted.some((alert) => alert.sticky),
		sources: [...new Set([...current.sources, ...toasted.map((alert) => alert.source)])],
		sounded: highest(SOUNDS, [current.sounded, sound]),
	};
	return {
		burst: next,
		toast: toasted.length
			? {
					id: next.id,
					count: next.count,
					level: next.level,
					sticky: next.sticky,
					source: next.sources.length === 1 ? next.sources[0] : null,
			  }
			: null,
		sound: next.sounded === current.sounded ? null : sound,
	};
}

// The most pressing of `values` in `order`, ignoring null; null when there is none.
function highest(order, values) {
	return values.reduce(
		(top, value) => (order.indexOf(value) > order.indexOf(top) ? value : top),
		null
	);
}
