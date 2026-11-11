import { ANNOUNCEMENTS } from "./announcements.js";

const COUNT_CAP = 99;

// A counter as text: "" for none, and "99+" once it passed the cap or the source capped it.
export function countText(count, capped = false) {
	if (!count) return "";
	return capped || count > COUNT_CAP ? `${COUNT_CAP}+` : String(count);
}

// What the launcher and the tab title show for a summary: the action count as text ("" when there is none),
// whether attention items exist, and whether an info source or the announcements have something new [FR-UI-01,
// FR-UI-06]. The announcements count among the action sources, yet a new one may ask for no acknowledgement: their
// dot points to the Announcements tab like an info tab's (§7.8).
export function badge(summary) {
	if (!summary) return { count: "", attention: false, unseen: false };
	const { totals, sources } = summary;
	return {
		count: countText(
			totals.action,
			sources.some((source) => source.kind === "action" && source.capped)
		),
		attention: totals.attention > 0,
		unseen:
			totals.info_new > 0 ||
			sources.some((source) => source.key === ANNOUNCEMENTS && source.new_since > 0),
	};
}
