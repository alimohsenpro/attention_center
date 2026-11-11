// Copyright (c) 2026, Attention Center Contributors and contributors
// For license information, please see license.txt

const TONE_FIELDS = ["default_tone", "urgent_tone", "immediate_tone", "reminder_tone"];

frappe.ui.form.on("Attention Center Settings", {
	refresh(frm) {
		// The controller's onload sends the tones of tones.json with their labels.
		const tones = frm.doc.__onload?.tones;
		if (tones) {
			for (const fieldname of TONE_FIELDS) frm.set_df_property(fieldname, "options", tones);
		}
		// The desk reads the settings in its boot.
		frm.set_intro(__("Users get changed settings the next time they load the desk."), "blue");
	},
});
