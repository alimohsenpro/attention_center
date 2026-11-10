import { element } from "../util/dom.js";
import { roveIndex } from "../util/keys.js";

// The tab strip of the window [FR-UI-02, FR-UI-08]: ARIA tabs with a roving tabindex. The arrow keys, Home and
// End move focus; Enter, Space or a click selects. Selecting fetches items from the server, so focus alone
// does not select (manual activation).
export function createTabs(parent, { panelId, safe, onSelect }) {
	const list = element("div", "tabs");
	list.setAttribute("role", "tablist");
	list.setAttribute("aria-label", __("Sources", null, "Attention Center"));
	parent.append(list);
	let buttons = [];

	list.addEventListener(
		"keydown",
		safe((event) => {
			const index = buttons.indexOf(event.target);
			const rtl = getComputedStyle(list).direction === "rtl";
			const next = index < 0 ? -1 : roveIndex(event.key, index, buttons.length, rtl);
			if (next < 0) return;
			event.preventDefault();
			focusAt(next);
		})
	);

	function focusAt(index) {
		buttons.forEach((button, i) => (button.tabIndex = i === index ? 0 : -1));
		buttons[index].focus();
	}

	function selectedIndex() {
		return buttons.findIndex((button) => button.getAttribute("aria-selected") === "true");
	}

	function tabButton(tab, index, selected) {
		const button = element("button", "tab");
		button.type = "button";
		button.id = `ac-tab-${index}`;
		button.dataset.id = tab.id;
		button.setAttribute("role", "tab");
		button.setAttribute("aria-controls", panelId);
		button.setAttribute("aria-selected", String(selected));
		button.tabIndex = selected ? 0 : -1;
		button.toggleAttribute("data-attention", tab.attention);

		button.append(element("span", null, tab.label));
		if (tab.counter) button.append(element("span", "tab-count", tab.counter));
		if (tab.unseen) {
			button.append(
				element("span", "tab-dot"),
				element("span", "visually-hidden", __("New", null, "Attention Center"))
			);
		}
		button.addEventListener(
			"click",
			safe(() => onSelect(tab.id))
		);
		return button;
	}

	return {
		// Draws the tabs. The tab that had focus keeps it, so a new summary does not move a keyboard user.
		render(tabs, selectedId) {
			const focused = list.getRootNode().activeElement;
			const focusedId = buttons.includes(focused) ? focused.dataset.id : null;
			buttons = tabs.map((tab, index) => tabButton(tab, index, tab.id === selectedId));
			list.replaceChildren(...buttons);
			const index = buttons.findIndex((button) => button.dataset.id === focusedId);
			if (index >= 0) focusAt(index);
		},
		// The id of the selected tab's element, which labels the panel.
		selectedElementId: () => buttons[selectedIndex()]?.id,
		focusSelected() {
			const index = selectedIndex();
			if (index >= 0) focusAt(index);
		},
	};
}
