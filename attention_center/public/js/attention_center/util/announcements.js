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
	let answer;
	try {
		answer = await fetchItems(ANNOUNCEMENTS, 0, ARRIVALS_PAGE);
	} catch {
		return alerts;
	}
	if (answer?.state !== "ok") return alerts;
	const since = previous.sources.find((source) => source.key === ANNOUNCEMENTS)?.latest;
	const priority = arrivedPriority(answer.items, since);
	if (!priority) return alerts;
	const raised = raiseAlert(alert, priority, { prefs, now });
	return alerts.map((candidate) => (candidate === alert ? raised : candidate));
}
