import { escapeHtml } from "../util/escape.js";
import { ICONS } from "./icons.js";

// The floating control at the bottom inline-end corner [FR-UI-01]: the action count, a dot while an info
// source has something new, and a toggle that collapses it to an icon.
export function createLauncher(root, { onOpen, onToggleCollapsed }) {
	const element = document.createElement("div");
	element.className = "launcher";
	element.innerHTML = `
		<button type="button" class="launcher-toggle">${ICONS.chevron}</button>
		<button type="button" class="launcher-main" aria-expanded="false">
			<span class="launcher-icon">${ICONS.bell}<span class="launcher-dot" hidden></span></span>
			<span class="launcher-label">${escapeHtml(__("Attention Center"))}</span>
			<span class="launcher-count" hidden></span>
		</button>`;
	const [toggle, main] = element.children;
	const dot = element.querySelector(".launcher-dot");
	const count = element.querySelector(".launcher-count");
	toggle.addEventListener("click", onToggleCollapsed);
	main.addEventListener("click", onOpen);
	root.append(element);

	return {
		render({ badge, collapsed, open }) {
			element.toggleAttribute("data-collapsed", collapsed);
			element.toggleAttribute("data-attention", badge.attention);
			count.textContent = badge.count;
			count.hidden = !badge.count;
			dot.hidden = !badge.unseen;
			main.setAttribute("aria-label", mainLabel(badge));
			main.setAttribute("aria-expanded", String(open));
			const toggleLabel = collapsed ? __("Expand the launcher") : __("Collapse the launcher");
			toggle.setAttribute("aria-label", toggleLabel);
			toggle.title = toggleLabel;
		},
	};
}

function mainLabel({ count, unseen }) {
	if (count && unseen) {
		return __(
			"Attention Center: {0} items need your action, and new information is waiting",
			[count]
		);
	}
	if (count) return __("Attention Center: {0} items need your action", [count]);
	if (unseen) return __("Attention Center: new information is waiting");
	return __("Attention Center");
}
