// Copyright (c) 2026, Attention Center Contributors and contributors
// For license information, please see license.txt

// What an admin may change on a source declared in an app's hooks; the server refuses changes to everything
// else [FR-SRC-01 AC2].
const ADMIN_FIELDS = ["enabled", "sort_order", "label", "roles", "user_groups"];
const MANAGER_ROLES = ["System Manager", "Attention Manager"];

frappe.ui.form.on("Attention Source", {
	refresh(frm) {
		const system = Boolean(frm.doc.is_system);
		frm.toggle_display(["is_system", "app"], system);
		// Python sources come from hooks only [FR-SRC-03 AC2]: a source made here is a DocType Query.
		frm.toggle_enable("source_type", false);
		if (system) {
			frm.toggle_enable(definition_fields(frm), false);
			frm.set_intro(
				__(
					"This source comes from the hooks of the app {0}. Only Enabled, Sort Order, Label and the targeting can be changed here.",
					[frappe.utils.escape_html(frm.doc.app)]
				),
				"blue"
			);
		}
		if (!frm.is_new() && frappe.user.has_role(MANAGER_ROLES)) {
			frm.add_custom_button(__("Test for my user"), () => test_source(frm));
		}
	},
});

function definition_fields(frm) {
	return frm.meta.fields
		.filter(
			(df) =>
				!frappe.model.no_value_type.includes(df.fieldtype) &&
				!ADMIN_FIELDS.includes(df.fieldname)
		)
		.map((df) => df.fieldname);
}

// Runs the saved definition for the session user with their own permissions [FR-SRC-02 AC2].
function test_source(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the source first: the test runs its saved definition."));
		return;
	}
	frappe.call({
		method: "attention_center.api.test_source",
		args: { source: frm.doc.name },
		freeze: true,
		freeze_message: __("Testing…"),
		callback: ({ message }) => show_result(message),
	});
}

function show_result({ count, items, duration_ms }) {
	const failed = count.state === "error" || items.state === "error";
	const dialog = new frappe.ui.Dialog({
		title: __("Test for my user"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "result" }],
	});
	dialog.fields_dict.result.$wrapper.html(`
		<p class="text-muted">${__(
			"The test uses your own permissions, even when the source is disabled or meant for other users. Other users may get other items."
		)}</p>
		${failed ? failure_html() : counts_html(count) + items_html(items.items)}
		<p class="text-muted small">${__("Ran in {0} ms", [cint(duration_ms)])}</p>
	`);
	dialog.show();
}

function failure_html() {
	return `<p class="text-danger">${__(
		"The source failed for your user. The server log names the error with the key of this source."
	)}</p>`;
}

function counts_html(count) {
	const total = count.capped ? "99+" : count.count;
	return `<p>
		<strong>${__("Items for you: {0}", [total])}</strong>
		· ${__("Urgent: {0}", [count.urgent])}
		· ${__("Immediate: {0}", [count.immediate])}
		· ${__("Overdue: {0}", [count.overdue])}
	</p>`;
}

function items_html(items) {
	if (!items.length) {
		return `<p>${__("Nothing is waiting on you")}</p>`;
	}
	const escape = frappe.utils.escape_html;
	const rows = items.map(
		(item) => `<tr>
			<td><a href="${escape(item.route)}" target="_blank" rel="noopener">${escape(item.title)}</a></td>
			<td>${escape(item.from_label || "")}</td>
			<td>${item.date ? escape(item_age(item.date)) : ""}</td>
			<td>${priority_html(item)}</td>
		</tr>`
	);
	return `<p>${__("First items:")}</p>
		<table class="table table-bordered">
			<thead><tr>
				<th>${__("Item", null, "Attention Center")}</th>
				<th>${__("From", null, "Attention Center")}</th>
				<th>${__("Date", null, "Attention Center")}</th>
				<th>${__("Priority", null, "Attention Center")}</th>
			</tr></thead>
			<tbody>${rows.join("")}</tbody>
		</table>`;
}

// As the window shows it: the relative age, or the date when the age has no wording.
function item_age(iso) {
	return frappe.datetime.prettyDate(iso) || frappe.datetime.str_to_user(iso.replace("T", " "));
}

function priority_html(item) {
	const pills = {
		immediate: pill("red", __("Immediate", null, "Attention Center")),
		urgent: pill("orange", __("Urgent", null, "Attention Center")),
	};
	const priority = pills[item.priority] || pill("gray", __("Normal", null, "Attention Center"));
	return item.overdue
		? `${priority} ${pill("red", __("Overdue", null, "Attention Center"))}`
		: priority;
}

function pill(color, text) {
	return `<span class="indicator-pill no-indicator-dot ${color}">${text}</span>`;
}
