import { element, textButton } from "../util/dom.js";
import { fromInputValue, msUntil, remindAt, toInputValue } from "../util/time.js";
import { ICONS } from "./icons.js";

let count = 0;

// "Remind me later" on an item [FR-SNZ-01]: a button for the item's row, and a row under it that the button shows and
// hides, with "In 1 hour", "Tomorrow morning" and a time the user picks. The reminder is Frappe's Reminder about the
// item's title and document, set through `remind` (api.remindMeLater); Frappe notifies the user when it falls due, and
// the due reminders source lists it. Times are chosen in the user's time zone and sent in the system time zone, like
// Do Not Disturb (§7.6).
//
// `columns` is the number of the table's columns, which the row spans; `format.date(iso)` shows a time; `safe` wraps
// every handler in the client's guard; `announce(text)` speaks through the polite live region.
export function createSnooze(item, { columns, remind, format, safe, announce }) {
	const id = `ac-snooze-${++count}`;
	const label = __("Remind me later about {0}", [item.title]);
	const toggle = element("button", "pager-button snooze-button");
	toggle.type = "button";
	toggle.innerHTML = ICONS.clock;
	toggle.title = __("Remind me later");
	toggle.setAttribute("aria-label", label);
	toggle.setAttribute("aria-expanded", "false");
	toggle.setAttribute("aria-controls", id);

	const hour = textButton(__("In 1 hour"));
	const morning = textButton(__("Tomorrow morning"));
	const at = document.createElement("input");
	at.type = "datetime-local";
	at.id = `${id}-at`;
	at.className = "snooze-input";
	const atLabel = element("label", "snooze-label", __("Another time"));
	atLabel.htmlFor = at.id;
	const set = textButton(__("Set reminder"));
	const status = element("p", "snooze-status");
	const group = element("div", "snooze");
	group.setAttribute("role", "group");
	group.setAttribute("aria-label", label);
	group.append(hour, morning, atLabel, at, set, status);
	const cell = element("td");
	cell.colSpan = columns;
	cell.append(group);
	const row = element("tr", "snooze-row");
	row.id = id;
	row.hidden = true;
	row.append(cell);

	let pending = false;

	toggle.addEventListener(
		"click",
		safe(() => {
			row.hidden = !row.hidden;
			toggle.setAttribute("aria-expanded", String(!row.hidden));
			at.min = toInputValue(frappe.datetime.now_datetime());
		})
	);
	hour.addEventListener(
		"click",
		safe(() => submit(remindAt("hour", frappe.datetime.now_datetime())))
	);
	morning.addEventListener(
		"click",
		safe(() => submit(remindAt("morning", frappe.datetime.now_datetime())))
	);
	set.addEventListener(
		"click",
		safe(() => {
			const chosen = fromInputValue(at.value);
			if (chosen && msUntil(chosen, frappe.datetime.now_datetime()) > 0) submit(chosen);
			else say(__("Choose a time later than now."));
		})
	);

	// `time` is in the user's time zone. A press while a reminder is being set is ignored, so that one press sets one.
	function submit(time) {
		if (pending) return;
		pending = true;
		setBusy(true);
		status.textContent = __("Saving…", null, "Attention Center");
		remind({
			remind_at: frappe.datetime.convert_to_system_tz(time),
			title: item.title,
			reference_doctype: item.reference_doctype,
			reference_name: item.reference_name,
		})
			.then(
				safe(({ remind_at }) => {
					const time = format.date(remind_at);
					say(__("Reminder set for {0}.", [time]));
				}),
				safe(() => say(__("The reminder could not be set. Try again.")))
			)
			.finally(
				safe(() => {
					pending = false;
					setBusy(false);
				})
			);
	}

	// The buttons keep focus while a reminder is being set: aria-disabled rather than disabled.
	function setBusy(busy) {
		for (const button of [hour, morning, set])
			button.setAttribute("aria-disabled", String(busy));
	}

	function say(text) {
		status.textContent = text;
		announce(text);
	}

	return { toggle, row };
}
