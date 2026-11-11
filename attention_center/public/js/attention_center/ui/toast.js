import { element } from "../util/dom.js";
import { ICONS } from "./icons.js";

// At most this many toasts are stacked above the launcher (docs/DESIGN_TOKENS.md).
const MAX_TOASTS = 3;
const DISMISS_MS = 8000;

// The toasts above the launcher [FR-UI-07]: a card per alert with an icon, one line of text, a "View" action
// and a close button. A toast never takes focus; it goes away by itself after a few seconds unless it is
// sticky, and a click on it opens the window on its tab. Urgent and immediate toasts carry the priority as a
// worded label, not only a colour, and every toast is spoken through the polite live region.
//
// `onOpen(tab)` opens the window on a tab (null for "All"); `safe` wraps every handler and timer in the
// client's guard; `announce(text)` speaks through the live region.
export function createToasts(root, { onOpen, safe, announce }) {
	const stack = element("div", "toasts");
	root.append(stack);
	// The toasts shown, oldest first, by id.
	const shown = new Map();

	function dismiss(id) {
		const toast = shown.get(id);
		if (!toast) return;
		clearTimeout(toast.timer);
		toast.node.remove();
		shown.delete(id);
	}

	function create(id, sticky) {
		if (shown.size >= MAX_TOASTS) {
			const drop = toastToDrop([...shown.values()], sticky);
			if (!drop) return null;
			dismiss(drop.id);
		}
		const node = element("div", "toast");
		const text = element("span", "toast-text");
		const view = element("button", "toast-action", __("View", null, "Attention Center"));
		view.type = "button";
		const close = element("button", "toast-close");
		close.type = "button";
		close.innerHTML = ICONS.x;
		const closeLabel = __("Close", null, "Attention Center");
		close.setAttribute("aria-label", closeLabel);
		close.title = closeLabel;
		const icon = element("span", "toast-icon");
		node.append(icon, text, view, close);
		// A press on a toast leaves focus where it was: inside the modal dialog, whose focus trap and Escape
		// would stop working once the pressed button is removed, or in the field the user is typing in.
		node.addEventListener(
			"mousedown",
			safe((event) => event.preventDefault())
		);
		node.addEventListener(
			"click",
			safe((event) => {
				const toast = shown.get(id);
				dismiss(id);
				if (!close.contains(event.target)) onOpen(toast.tab);
			})
		);
		stack.append(node);
		const toast = { id, node, icon, text, timer: null };
		shown.set(id, toast);
		return toast;
	}

	// Shows the toast with this id, or updates it in place when it is still shown. A new toast that finds no room
	// (toastToDrop) is not shown.
	function show({ id, text, level, sticky, tab }) {
		const toast = shown.get(id) ?? create(id, sticky);
		if (!toast) return;
		Object.assign(toast, { sticky, tab });
		toast.node.dataset.level = level;
		toast.icon.innerHTML = level === "normal" ? ICONS.bell : ICONS.alert;
		const label = levelLabel(level);
		toast.text.replaceChildren();
		if (label) toast.text.append(element("span", "toast-pill", label));
		toast.text.append(text);
		clearTimeout(toast.timer);
		const leave = safe(() => dismiss(id));
		toast.timer = sticky ? null : setTimeout(leave, DISMISS_MS);
		announce(spokenText(level, text));
	}

	return { show };
}

// The text of a toast for new items: their number and, when they all come from one source, its label.
export function newItemsText(count, sourceLabel) {
	if (!sourceLabel) return __("{0} new items", [count]);
	if (count === 1) return __("New item in {0}", [sourceLabel]);
	return __("{0} new items in {1}", [count, sourceLabel]);
}

// The toast that makes room for a new one: the oldest that is not sticky. When all are sticky, only a sticky
// newcomer replaces the oldest; for any other the answer is null and the newcomer is not shown, so an
// immediate toast stays until it is answered. `toasts` are {sticky} objects, oldest first.
export function toastToDrop(toasts, newcomerSticky) {
	return toasts.find((toast) => !toast.sticky) ?? (newcomerSticky ? toasts[0] : null);
}

function levelLabel(level) {
	if (level === "immediate") return __("Immediate", null, "Attention Center");
	if (level === "urgent") return __("Urgent", null, "Attention Center");
	return "";
}

function spokenText(level, text) {
	if (level === "immediate") return __("Immediate: {0}", [text]);
	if (level === "urgent") return __("Urgent: {0}", [text]);
	return text;
}
