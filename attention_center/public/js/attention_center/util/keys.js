// Keyboard rules of the window [FR-UI-08]. No DOM and no frappe, so they can be tested with node --test.

// The tab to focus after a key in the tab list, or -1 for a key the list does not handle. The arrow keys
// follow the reading direction (in right-to-left text the next tab is on the left) and wrap around;
// Home and End go to the first and the last tab.
export function roveIndex(key, index, count, rtl) {
	const next = rtl ? "ArrowLeft" : "ArrowRight";
	const previous = rtl ? "ArrowRight" : "ArrowLeft";
	switch (key) {
		case next:
			return (index + 1) % count;
		case previous:
			return (index - 1 + count) % count;
		case "Home":
			return 0;
		case "End":
			return count - 1;
		default:
			return -1;
	}
}

// The keys the window keeps from the desk: their keydown stops in the window, in every display mode and on any of
// its elements. The desk's handlers on `window` would act on the page behind it: Escape closes a form dialog or grid
// row there, and on a list page the Up and Down arrows focus a list row and cancel what the key does in the window
// (move a radio choice, the select, the slider, the tab list, or scroll). Every other key, the window's own
// shortcut included, still reaches the desk.
const KEPT_KEYS = new Set([
	"Escape",
	"ArrowUp",
	"ArrowDown",
	"ArrowLeft",
	"ArrowRight",
	"Home",
	"End",
	"PageUp",
	"PageDown",
]);

export function keepsKey(key) {
	return KEPT_KEYS.has(key);
}

// The focus trap of the dialog: the element Tab (or Shift+Tab when `backwards`) must focus, as an index
// into its `count` focusable elements, or -1 to let the browser move focus. `index` is the focused element,
// -1 when focus is on none of them.
export function trapIndex(index, count, backwards) {
	if (backwards) return index <= 0 ? count - 1 : -1;
	return index < 0 || index === count - 1 ? 0 : -1;
}
