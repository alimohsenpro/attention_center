export const COUNT_CAP = 99;

// What the launcher and the tab title show for a summary: the action count as text ("" when there is none),
// whether attention items exist, and whether an info source has something new [FR-UI-01, FR-UI-06].
export function badge(summary) {
	if (!summary) return { count: "", attention: false, unseen: false };
	const { totals, sources } = summary;
	const capped =
		totals.action > COUNT_CAP ||
		sources.some((source) => source.kind === "action" && source.capped);
	return {
		count: totals.action > 0 ? (capped ? `${COUNT_CAP}+` : String(totals.action)) : "",
		attention: totals.attention > 0,
		unseen: totals.info_new > 0,
	};
}
