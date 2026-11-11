import assert from "node:assert/strict";
import test from "node:test";

import { ANNOUNCEMENTS } from "../../attention_center/public/js/attention_center/util/announcements.js";
import { badge } from "../../attention_center/public/js/attention_center/util/badge.js";

function summary({ action = 0, attention = 0, info_new = 0, sources = [] }) {
	return {
		generated_at: "2026-11-10T09:00:00",
		sources,
		totals: { action, attention, info_new },
	};
}

const source = (kind, count, capped = false) => ({ key: `test_app.${kind}`, kind, count, capped });

const CASES = [
	["no summary yet", null, { count: "", attention: false, unseen: false }],
	["nothing waiting", summary({}), { count: "", attention: false, unseen: false }],
	[
		"action items",
		summary({ action: 5, sources: [source("action", 5)] }),
		{ count: "5", attention: false, unseen: false },
	],
	[
		"exactly the cap",
		summary({ action: 99, sources: [source("action", 99)] }),
		{ count: "99", attention: false, unseen: false },
	],
	[
		"a capped action source",
		summary({ action: 99, sources: [source("action", 99, true)] }),
		{ count: "99+", attention: false, unseen: false },
	],
	[
		"several sources above the cap together",
		summary({ action: 150, sources: [source("action", 99), source("action", 51)] }),
		{ count: "99+", attention: false, unseen: false },
	],
	[
		"a capped info source does not cap the action count",
		summary({
			action: 4,
			info_new: 99,
			sources: [source("action", 4), source("info", 99, true)],
		}),
		{ count: "4", attention: false, unseen: true },
	],
	[
		"attention items",
		summary({ action: 2, attention: 1, sources: [source("action", 2)] }),
		{ count: "2", attention: true, unseen: false },
	],
	[
		"only new info",
		summary({ info_new: 3, sources: [source("info", 3)] }),
		{ count: "", attention: false, unseen: true },
	],
	[
		"a new announcement that asks for no acknowledgement",
		summary({ sources: [{ ...source("action", 0), key: ANNOUNCEMENTS, new_since: 1 }] }),
		{ count: "", attention: false, unseen: true },
	],
	[
		"announcements all seen",
		summary({
			action: 1,
			sources: [{ ...source("action", 1), key: ANNOUNCEMENTS, new_since: 0 }],
		}),
		{ count: "1", attention: false, unseen: false },
	],
	[
		"new items in another action source",
		summary({ action: 2, sources: [{ ...source("action", 2), new_since: 2 }] }),
		{ count: "2", attention: false, unseen: false },
	],
];

for (const [name, input, expected] of CASES) {
	test(`badge: ${name}`, () => {
		assert.deepEqual(badge(input), expected);
	});
}
