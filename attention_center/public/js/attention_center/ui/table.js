import { isDeskRoute } from "../util/route.js";
import { ICONS } from "./icons.js";

// The items of a tab as a table [FR-UI-02]: item, type (and source in the All tab), from, date, priority and
// due date, status, and an "Open" link. Every value is set as text. Overdue, urgent and immediate rows carry a
// worded label with an icon, not only a colour (AC2).
//
// `entries` are {source, item} pairs; `sourceLabel(key)` names a source; `format` has `age(iso)` and
// `date(iso)`; `onOpen(route)` opens an item after a plain click (a click with a modifier key or the middle
// button is left to the browser, which opens the link in a new tab); `safe` wraps the event handlers.
export function renderTable(entries, { showSource, sourceLabel, format, onOpen, safe }) {
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
	for (const heading of headings) head.append(cell("th", heading));
	const openHeading = cell("th");
	openHeading.append(text("span", __("Open", null, "Attention Center"), "visually-hidden"));
	head.append(openHeading);
	for (const th of head.cells) th.scope = "col";

	const body = table.createTBody();
	const onClick = safe(onOpenClick(onOpen));
	for (const { source, item } of entries) {
		body.append(row(item, showSource ? sourceLabel(source) : null, format, onClick));
	}
	const wrapper = document.createElement("div");
	wrapper.className = "table-wrap";
	wrapper.append(table);
	return wrapper;
}

function row(item, sourceName, format, onClick) {
	const tr = document.createElement("tr");
	tr.toggleAttribute("data-overdue", item.overdue);
	tr.dataset.priority = item.priority;

	const title = cell("td");
	title.className = "cell-item";
	title.append(text("span", item.title, "item-title"));

	const type = cell("td");
	if (item.type_label) type.append(text("span", item.type_label));
	if (sourceName) type.append(text("span", sourceName, "muted"));

	tr.append(title, type, cell("td", item.from_label), dateCell(item.date, format));
	tr.append(priorityCell(item, format), statusCell(item), openCell(item, onClick));
	return tr;
}

function dateCell(iso, format) {
	const td = cell("td");
	if (iso) {
		const time = text("time", format.age(iso));
		time.dateTime = iso;
		time.title = format.date(iso);
		td.append(time);
	}
	return td;
}

function priorityCell(item, format) {
	const td = cell("td");
	if (item.priority === "immediate") td.append(pill(__("Immediate"), "immediate"));
	else if (item.priority === "urgent") td.append(pill(__("Urgent"), "urgent"));
	else td.append(text("span", __("Normal", null, "Attention Center"), "muted"));
	if (item.overdue) td.append(pill(__("Overdue", null, "Attention Center"), "overdue"));
	else if (item.due) td.append(text("span", __("Due {0}", [format.date(item.due)]), "muted"));
	return td;
}

function statusCell(item) {
	const td = cell("td");
	if (item.status_label) {
		const status = text("span", item.status_label, "status");
		status.dataset.color = item.status_color;
		td.append(status);
	}
	return td;
}

function onOpenClick(onOpen) {
	return (event) => {
		if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)
			return;
		event.preventDefault();
		onOpen(event.currentTarget.getAttribute("href"));
	};
}

function openCell(item, onClick) {
	const td = cell("td");
	if (!isDeskRoute(item.route)) return td;
	const link = text("a", __("Open", null, "Attention Center"), "open-link");
	link.href = item.route;
	link.setAttribute("aria-label", __("Open {0}", [item.title]));
	link.addEventListener("click", onClick);
	td.append(link);
	return td;
}

function pill(label, kind) {
	const element = document.createElement("span");
	element.className = "pill";
	element.dataset.kind = kind;
	element.innerHTML = ICONS.alert;
	element.append(text("span", label));
	return element;
}

function cell(tag, value) {
	const element = document.createElement(tag);
	if (value) element.textContent = value;
	return element;
}

function text(tag, value, className) {
	const element = document.createElement(tag);
	element.textContent = value;
	if (className) element.className = className;
	return element;
}
