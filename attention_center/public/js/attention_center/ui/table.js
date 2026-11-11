import { element } from "../util/dom.js";
import { isDeskRoute } from "../util/route.js";
import { ICONS } from "./icons.js";

// The items of a tab as a table [FR-UI-02]: item, type (and source in the All tab), from, date, priority and
// due date, status, and an "Open" link. Every value is set as text. Overdue, urgent and immediate rows carry a
// worded label with an icon, not only a colour (AC2). Below 720 px of window width the stylesheet shows each
// row as a card instead [FR-UI-04]; each cell's class names its place in the card.
//
// `entries` are {source, item} pairs; `sourceLabel(key)` names a source; `format` has `age(iso)` and
// `date(iso)`; `onOpenClick(event, entry)` handles a click on an item's "Open" link, whose href is the item's
// route; `snooze(item, columns)` gives the item's "Remind me later" button, placed beside "Open", and the row under
// the item's that it shows (ui/snooze.js).
export function renderTable(entries, { showSource, sourceLabel, format, onOpenClick, snooze }) {
	const table = document.createElement("table");
	const head = table.createTHead().insertRow();
	const headings = [
		__("Item", null, "Attention Center"),
		__("Type", null, "Attention Center"),
		__("From", null, "Attention Center"),
		__("Date", null, "Attention Center"),
		__("Priority", null, "Attention Center"),
		__("Status", null, "Attention Center"),
	];
	for (const heading of headings) head.append(element("th", null, heading));
	const openHeading = element("th");
	openHeading.append(element("span", "visually-hidden", __("Open", null, "Attention Center")));
	head.append(openHeading);
	for (const th of head.cells) th.scope = "col";

	const body = table.createTBody();
	for (const entry of entries) {
		const control = snooze(entry.item, head.cells.length);
		const sourceName = showSource ? sourceLabel(entry.source) : null;
		body.append(row(entry, sourceName, format, onOpenClick, control.toggle), control.row);
	}
	const wrapper = element("div", "table-wrap");
	wrapper.append(table);
	return wrapper;
}

function row(entry, sourceName, format, onClick, snoozeToggle) {
	const { item } = entry;
	const tr = element("tr");
	tr.toggleAttribute("data-overdue", item.overdue);
	tr.dataset.priority = item.priority;

	const title = element("td", "cell-item");
	title.append(element("span", "item-title", item.title));

	const type = element("td", "cell-type");
	if (item.type_label) type.append(element("span", null, item.type_label));
	if (sourceName) type.append(element("span", "muted", sourceName));

	const from = element("td", "cell-from", item.from_label);
	tr.append(title, type, from, dateCell(item.date, format));
	const open = openCell(entry, onClick);
	open.append(snoozeToggle);
	tr.append(priorityCell(item, format), statusCell(item), open);
	return tr;
}

function dateCell(iso, format) {
	const td = element("td", "cell-date");
	if (iso) {
		const time = element("time", null, format.age(iso));
		time.dateTime = iso;
		time.title = format.date(iso);
		td.append(time);
	}
	return td;
}

function priorityCell(item, format) {
	const td = element("td", "cell-priority");
	td.append(priorityLabel(item.priority));
	if (item.overdue) {
		td.append(pill(__("Overdue", null, "Attention Center"), "overdue"));
	} else if (item.due) {
		// A call among the arguments of __() hides the context from Frappe's string extraction.
		const date = format.date(item.due);
		td.append(element("span", "muted", __("Due {0}", [date], "Attention Center")));
	}
	return td;
}

function priorityLabel(priority) {
	if (priority === "immediate") return pill(__("Immediate", null, "Attention Center"), priority);
	if (priority === "urgent") return pill(__("Urgent", null, "Attention Center"), priority);
	return element("span", "muted", __("Normal", null, "Attention Center"));
}

function statusCell(item) {
	const td = element("td", "cell-status");
	if (item.status_label) {
		const status = element("span", "status", item.status_label);
		status.dataset.color = item.status_color;
		td.append(status);
	}
	return td;
}

function openCell(entry, onClick) {
	const { item } = entry;
	const td = element("td", "cell-open");
	if (!isDeskRoute(item.route)) return td;
	const link = element("a", "open-link", __("Open", null, "Attention Center"));
	link.href = item.route;
	link.setAttribute("aria-label", __("Open {0}", [item.title], "Attention Center"));
	link.addEventListener("click", (event) => onClick(event, entry));
	td.append(link);
	return td;
}

function pill(label, kind) {
	const node = element("span", "pill");
	node.dataset.kind = kind;
	node.innerHTML = ICONS.alert;
	node.append(element("span", null, label));
	return node;
}
