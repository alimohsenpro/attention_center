// Copyright (c) 2026, Attention Center Contributors and contributors
// For license information, please see license.txt

frappe.query_reports["Announcement Acknowledgements"] = {
	filters: [
		{
			fieldname: "announcement",
			label: __("Announcement", null, "Attention Announcement Receipt"),
			fieldtype: "Link",
			options: "Attention Announcement",
			reqd: 1,
			// Only these have acknowledgements to show.
			get_query: () => ({ filters: { requires_acknowledgement: 1 } }),
		},
	],
};
