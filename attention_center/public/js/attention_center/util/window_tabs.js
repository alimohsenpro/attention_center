import { ANNOUNCEMENTS } from "./announcements.js";
import { badge, countText } from "./badge.js";
import { isDeskRoute } from "./route.js";

export const ALL_TAB = "all";

// The window's tabs for a summary [FR-UI-02]: "All", which merges the action sources, then one tab per action source,
// then the info sources, then Announcements [FR-ANN-02]. Each tab names the sources it shows, the sources viewing it
// marks seen, its counter text, whether it holds attention items (urgent, immediate or overdue), whether it has
// something new to read, and the source's own "view all" route.
//
// The announcements source is an action source, so "All" shows it, but only its announcements awaiting
// acknowledgement (itemFetcher). "All" therefore does not mark it seen: an announcement for information is new until
// the user opens the Announcements tab, which shows its dot meanwhile.
export function buildTabs(summary) {
	const sources = summary?.sources ?? [];
	const actions = sources.filter((source) => source.kind === "action");
	const { count, attention } = badge(summary);
	const all = {
		id: ALL_TAB,
		label: __("All", null, "Attention Center"),
		sources: actions.map((source) => source.key),
		marks: actions
			.filter((source) => source.key !== ANNOUNCEMENTS)
			.map((source) => source.key),
		counter: count,
		attention,
		unseen: false,
		listRoute: null,
	};
	const infos = sources.filter((source) => source.kind === "info");
	const isAnnouncements = (source) => source.key === ANNOUNCEMENTS;
	return [
		all,
		...actions.filter((source) => !isAnnouncements(source)).map(sourceTab),
		...infos.map(sourceTab),
		...actions.filter(isAnnouncements).map(sourceTab),
	];
}

// Where a tab gets a source's items: `api.getItems`, except that "All" lists only the announcements awaiting
// acknowledgement, the action items among them. `api` is the client's api (api.js).
export function itemFetcher(tab, api) {
	if (tab.id !== ALL_TAB) return api.getItems;
	return (key, start, size) =>
		key === ANNOUNCEMENTS
			? api.getAnnouncementsToAcknowledge(start, size)
			: api.getItems(key, start, size);
}

function sourceTab(source) {
	const ok = source.state === "ok";
	// New announcements may be for information only: like info sources they show a dot until seen.
	const readable = source.kind === "info" || source.key === ANNOUNCEMENTS;
	return {
		id: source.key,
		label: source.label,
		sources: [source.key],
		marks: [source.key],
		counter: ok ? countText(source.count, source.capped) : "",
		attention:
			ok &&
			source.kind === "action" &&
			source.urgent + source.immediate + source.overdue > 0,
		unseen: ok && readable && source.new_since > 0,
		listRoute: isDeskRoute(source.list_route) ? source.list_route : null,
	};
}
