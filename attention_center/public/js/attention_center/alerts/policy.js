// The alert policy [FR-ALERT-01..04, §7.4]: which new items deserve a toast and which a sound. Pure: it
// compares two summaries and reads the preferences, so it can be tested without a browser.

// The alert levels from least to most pressing; a burst takes the highest of its alerts (alerts/coalesce.js).
export const LEVELS = ["info", "normal", "urgent", "immediate"];

// What a new item of each level does, per FR-ALERT-02. `sound` names the tone's role: the user's standard
// tone, or the organisation's urgent or immediate tone, which plays at every sound scope; `scopes` are the
// sound scopes (prefs.sound_scope) in which the standard tone plays.
const RULES = {
	info: { toast: false, sound: "standard", scopes: ["Everything"] },
	normal: { toast: true, sound: "standard", scopes: ["Action Items", "Everything"] },
	urgent: { toast: true, sound: "urgent" },
	immediate: { toast: true, sound: "immediate" },
};

// The alerts for a new summary: one per source that gained items since `previous`, as
// {source, level, count, toast, sticky, sound}, `sound` being null when it stays silent.
//
// No alert comes from the first summary of the page load (`previous` null), nor from a change the user made
// themselves (`actor`, the author the nudges named, is the session `user`) [FR-ALERT-04]. Do Not Disturb
// silences the sounds and keeps the toasts. `now` is the current time as naive ISO text in the system time
// zone, the form of `prefs.dnd_until`.
export function newItemAlerts({ previous, summary, actor, user, prefs, now }) {
	if (!previous || actor === user) return [];
	const before = new Map(previous.sources.map((source) => [source.key, source]));
	const silent = dndActive(prefs.dnd_until, now);
	const alerts = [];
	for (const source of summary.sources) {
		const count = newCount(before.get(source.key), source);
		if (!count) continue;
		const level = alertLevel(before.get(source.key), source);
		const rule = RULES[level];
		alerts.push({
			source: source.key,
			level,
			count,
			toast: rule.toast,
			sticky: level === "immediate",
			sound: silent || (rule.scopes && !rule.scopes.includes(prefs.sound_scope)) ? null : rule.sound,
		});
	}
	return alerts;
}

// The periodic reminder's alert (FR-ALERT-02, last row): a toast and the organisation's reminder tone at
// every sound scope, silent during Do Not Disturb.
export function reminderAlert({ prefs, now }) {
	return {
		level: "reminder",
		toast: true,
		sticky: false,
		sound: dndActive(prefs.dnd_until, now) ? null : "reminder",
	};
}

// Whether Do Not Disturb lasts beyond `now`. Both are naive ISO text in the system time zone; the date and
// time separator is made the same, so that comparing the texts compares the times.
export function dndActive(dndUntil, now) {
	return Boolean(dndUntil) && dndUntil.replace(" ", "T") > now.replace(" ", "T");
}

// How many items a source gained: the growth of its count, or one when only its latest item is newer (an item
// arrived as another was handled, or the count stayed at its cap). A source that was absent or failing in the
// previous summary has no count to compare, so its items are not taken for new ones.
function newCount(before, source) {
	if (before?.state !== "ok" || source.state !== "ok") return 0;
	if (source.count > before.count) return source.count - before.count;
	return isLater(source.latest, before.latest) ? 1 : 0;
}

// ISO texts of one source share their form, so the later one sorts after the other.
function isLater(latest, before) {
	return Boolean(latest) && (!before || latest > before);
}

function alertLevel(before, source) {
	if (source.kind === "info") return "info";
	if (source.immediate > before.immediate) return "immediate";
	if (source.urgent > before.urgent) return "urgent";
	return "normal";
}
