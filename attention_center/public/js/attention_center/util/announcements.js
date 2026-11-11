import { raiseAlert } from "../alerts/policy.js";

// The built-in announcements source (§4.5). Its items are every announcement the user receives; only those awaiting
// their acknowledgement are action items, and only those count as urgent or immediate [FR-ANN-02].
export const ANNOUNCEMENTS = "attention_center.announcements";

const PRIORITY_RANK = { normal: 1, urgent: 2, immediate: 3 };
// The most items get_items gives at once: the announcements that just arrived are among the first of them.
const ARRIVALS_PAGE = 50;

// The most pressing priority among the announcements that arrived after `since`, the source's latest date in the
// previous summary; null when none did. Dates are naive ISO text in the system time zone, which sorts like the dates.
export function arrivedPriority(items, since) {
	return items
		.filter((item) => item.date && (!since || item.date > since))
		.reduce(
			(top, item) =>
				(PRIORITY_RANK[item.priority] ?? 0) > (PRIORITY_RANK[top] ?? 0)
					? item.priority
					: top,
			null
		);
}

// The alerts of a summary, the announcements' at the priority of the announcements that arrived: an immediate
// announcement that asks for no acknowledgement still raises the sticky toast and the immediate tone (alerts/policy.js,
// raiseAlert). `fetchItems(key, start, size)` answers like get_items; without an answer the alerts stay as they are.
export async function withAnnouncementPriority(alerts, previous, fetchItems, { prefs, now }) {
	const alert = alerts.find((candidate) => candidate.source === ANNOUNCEMENTS);
	if (!alert || alert.level === "immediate") return alerts;
	const items = await fetchAnnouncements(fetchItems);
	if (!items) return alerts;
	const since = previous.sources.find((source) => source.key === ANNOUNCEMENTS)?.latest;
	const priority = arrivedPriority(items, since);
	if (!priority) return alerts;
	const raised = raiseAlert(alert, priority, { prefs, now });
	return alerts.map((candidate) => (candidate === alert ? raised : candidate));
}

// The store.onSummary listener that raises the sticky toast of FR-ANN-02 on the first summary of the page load, when
// an immediate announcement is among those the user has not seen yet: one published while they were away, or whose
// toast a reload dropped. The server tells which those are: published since the user last viewed the Announcements
// tab, and neither acknowledged nor written by them. No later summary raises it (those compare with the previous one,
// newItemAlerts). `fetchUnseen()` answers like get_unseen_announcements; `show(count)` shows the toast for the
// `count` announcements not seen yet. A failed source or request shows nothing.
export function toastUnseenImmediate({ fetchUnseen, show }) {
	return async ({ previous, summary }) => {
		if (previous) return;
		const source = summary.sources.find((candidate) => candidate.key === ANNOUNCEMENTS);
		if (source?.state !== "ok" || !source.new_since) return;
		let unseen;
		try {
			unseen = await fetchUnseen();
		} catch {
			return;
		}
		if (unseen.immediate) show(unseen.count);
	};
}

// The first ARRIVALS_PAGE items of the source, or null without an answer.
async function fetchAnnouncements(fetchItems) {
	let answer;
	try {
		answer = await fetchItems(ANNOUNCEMENTS, 0, ARRIVALS_PAGE);
	} catch {
		return null;
	}
	return answer?.state === "ok" ? answer.items : null;
}
