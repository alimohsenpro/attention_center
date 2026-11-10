import { badge, countText } from "./badge.js";
import { isDeskRoute } from "./route.js";

export const ALL_TAB = "all";

// The window's tabs for a summary [FR-UI-02]: "All", which merges the action sources, then one tab per
// action source, then the info sources. Each tab names the sources it shows, its counter text, whether it
// holds attention items (urgent, immediate or overdue), whether an info source has something new, and the
// source's own "view all" route.
export function buildTabs(summary) {
	const sources = summary?.sources ?? [];
	const actions = sources.filter((source) => source.kind === "action");
	const { count, attention } = badge(summary);
	const all = {
		id: ALL_TAB,
		label: __("All", null, "Attention Center"),
		sources: actions.map((source) => source.key),
		counter: count,
		attention,
		unseen: false,
		listRoute: null,
	};
	const infos = sources.filter((source) => source.kind === "info");
	return [all, ...actions.map(sourceTab), ...infos.map(sourceTab)];
}

function sourceTab(source) {
	const ok = source.state === "ok";
	return {
		id: source.key,
		label: source.label,
		sources: [source.key],
		counter: ok ? countText(source.count, source.capped) : "",
		attention:
			ok &&
			source.kind === "action" &&
			source.urgent + source.immediate + source.overdue > 0,
		unseen: ok && source.kind === "info" && source.new_since > 0,
		listRoute: isDeskRoute(source.list_route) ? source.list_route : null,
	};
}
