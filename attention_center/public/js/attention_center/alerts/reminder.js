import { reminderAlert } from "./policy.js";

// The browser's tabs share the time of the last reminder here, so that one of them reminds per interval.
export const LAST_REMINDER_KEY = "attention_center:last_reminder";
const HOUR_MS = 3600 * 1000;
const CHECK_MS = 60 * 1000;
// A hidden tab reminds only this long after the reminder is due, so that a visible tab, which checks every minute,
// reminds instead whenever there is one: a toast in a hidden tab goes unseen. With no visible tab a hidden one
// still reminds, since its tone reaches a user working in another window.
const HIDDEN_DELAY_MS = 2 * CHECK_MS;

const SYSTEM_CLOCK = {
	now: () => Date.now(),
	setTimeout: (callback, ms) => setTimeout(callback, ms),
};

// The periodic reminder [FR-ALERT-06, §7.4]: while attention items (urgent, immediate or overdue) wait, every
// `intervalHours` one tab of the browser calls `remind(alert)` with the reminder's alert (policy.reminderAlert)
// and an `id` under which the tabs claim its sound. It shows a toast and plays a tone; it never opens the window.
// An interval of 0 turns the reminder off.
//
// A check runs every minute. The interval starts, without a reminder, when a check finds attention items after
// one that found none, and in a browser that never stored a reminder time: the first urgent item after a quiet
// spell brings its own alert, and a reminder right after it would repeat it.
//
// `store` holds the summary and the preferences; `storage` is localStorage, `page` the document
// (visibilityState); `systemNow()` is the current time as naive ISO text in the system time zone, the form of
// dnd_until; `safe` wraps every timer in the client's guard.
export function startReminder({
	intervalHours,
	store,
	storage,
	page,
	systemNow,
	remind,
	safe,
	clock = SYSTEM_CLOCK,
}) {
	const interval = intervalHours * HOUR_MS;
	// The time this tab last stored: it stands in for the storage when the storage refuses the write, so that the
	// tab then reminds once per interval on its own rather than at every check.
	let written = null;
	// Whether this tab's last check found attention items; null before its first check with a summary.
	let attention = null;

	function lastReminder() {
		const times = [Number.parseInt(storage.getItem(LAST_REMINDER_KEY), 10), written].filter(
			Number.isFinite
		);
		return times.length ? Math.max(...times) : null;
	}

	function save(at) {
		written = at;
		try {
			storage.setItem(LAST_REMINDER_KEY, String(at));
		} catch {
			// Full or disabled: the tab keeps its own time (above).
		}
	}

	function check() {
		const { summary, prefs } = store.get();
		if (!summary) return;
		const appeared = attention === false;
		attention = summary.totals.attention > 0;
		if (!attention) return;
		const now = clock.now();
		const last = lastReminder();
		if (last === null || appeared) {
			save(now);
			return;
		}
		const delay = page.visibilityState === "visible" ? 0 : HIDDEN_DELAY_MS;
		if (now < last + interval + delay) return;
		save(now);
		// Tabs that remind at the same moment read the same last time, so they claim the same sound.
		remind({ id: `reminder@${last}`, ...reminderAlert({ prefs, now: systemNow() }) });
	}

	function tick() {
		clock.setTimeout(safe(tick), CHECK_MS);
		check();
	}

	if (interval > 0) clock.setTimeout(safe(tick), CHECK_MS);

	return {
		// Starts the interval again: the window opened by itself at login, which reminds of everything waiting.
		restart() {
			if (interval > 0) save(clock.now());
		},
	};
}
