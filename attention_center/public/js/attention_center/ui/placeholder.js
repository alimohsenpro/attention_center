// Stands in for the window until it exists (M3-T2): the window title and the count of each source.
export function createPlaceholder(root) {
	const section = document.createElement("section");
	section.className = "placeholder";
	section.hidden = true;
	const heading = document.createElement("h2");
	heading.textContent = __("What needs your attention");
	const list = document.createElement("ul");
	section.append(heading, list);
	root.append(section);

	return {
		render({ summary, ui }) {
			section.hidden = !ui.open;
			list.replaceChildren(...(summary?.sources ?? []).map(sourceRow));
		},
	};
}

function sourceRow(source) {
	const row = document.createElement("li");
	const label = document.createElement("span");
	label.textContent = source.label;
	const count = document.createElement("span");
	count.textContent = source.state === "ok" ? source.count : "—";
	row.append(label, count);
	return row;
}
