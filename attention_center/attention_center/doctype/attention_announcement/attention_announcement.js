// Copyright (c) 2026, Attention Center Contributors and contributors
// For license information, please see license.txt

// Managers open the list of who acknowledged a saved announcement that asks for it [FR-ANN-04].
frappe.ui.form.on("Attention Announcement", {
	refresh(frm) {
		const manager = frappe.user.has_role(["System Manager", "Attention Manager"]);
		if (frm.is_new() || !frm.doc.requires_acknowledgement || !manager) return;
		frm.add_custom_button(__("Who acknowledged"), () =>
			frappe.set_route("query-report", "Announcement Acknowledgements", {
				announcement: frm.doc.name,
			})
		);
	},
});
