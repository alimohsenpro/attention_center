import { adoptStyles, element } from "../util/dom.js";
import { createFeed } from "../util/feed.js";
import { trapIndex } from "../util/keys.js";
import { routeArguments } from "../util/route.js";
import { ALL_TAB, buildTabs } from "../util/window_tabs.js";
import { ICONS } from "./icons.js";
import { renderTable } from "./table.js";
import { createTabs } from "./tabs.js";
import { WINDOW_STYLES } from "./window_styles.js";

const PANEL_ID = "ac-panel";
const TITLE_ID = "ac-window-title";
// Inactive tabs (tabindex -1) are left out: Tab reaches the tab list through its selected tab only.
const FOCUSABLE = ":is(button:not([disabled]), a[href], [tabindex]):not([tabindex='-1'])";

// The window in dialog mode [FR-UI-02, FR-UI-08]: a modal dialog with one tab per source and the "All" tab,
// the items of the selected tab page by page, and loading, empty and error states. It opens and closes with
// `store.ui.open`; focus stays inside while it is open and goes back where it was when it closes.
//
// `api` has getItems and markSeen; `safe` wraps every handler in the client's guard; `announce(text)` speaks
// through the polite live region; `refreshSummary()` fetches the summary into the store.
export function createWindow(root, { store, api, safe, announce, refreshSummary, pageSize }) {
	adoptStyles(root, WINDOW_STYLES);
	const overlay = element("div", "overlay");
	overlay.hidden = true;
	const dialog = element("section", "window");
	dialog.dataset.mode = "dialog";
	dialog.tabIndex = -1;
	dialog.setAttribute("role", "dialog");
	dialog.setAttribute("aria-modal", "true");
	dialog.setAttribute("aria-labelledby", TITLE_ID);

	const header = element("header", "window-header");
	const title = element("h2", "window-title", __("What needs your attention"));
	title.id = TITLE_ID;
	const closeButton = iconButton(ICONS.x, __("Close", null, "Attention Center"));
	header.append(title, closeButton);
	dialog.append(header);

	const tabs = createTabs(dialog, { panelId: PANEL_ID, safe, onSelect: select });
	const panel = element("div", "panel");
	panel.id = PANEL_ID;
	panel.setAttribute("role", "tabpanel");
	const toolbar = element("div", "panel-toolbar");
	const viewAll = element("a", "view-all");
	viewAll.append(element("span", null, __("View all", null, "Attention Center")));
	viewAll.insertAdjacentHTML("beforeend", ICONS.external);
	toolbar.append(viewAll);
	const content = element("div", "panel-content");
	const pager = element("nav", "pager");
	pager.setAttribute("aria-label", __("Pages", null, "Attention Center"));
	const previous = textButton(__("Previous", null, "Attention Center"));
	const pageLabel = element("span", "page-label");
	const next = textButton(__("Next", null, "Attention Center"));
	pager.append(previous, pageLabel, next);
	panel.append(toolbar, content, pager);
	dialog.append(panel);
	overlay.append(dialog);
	root.append(overlay);

	let selected = ALL_TAB;
	let page = 0;
	let loading = false;
	// Raised by every load and by closing, so that a late answer for another tab or page is not drawn.
	let generation = 0;
	let feeds = new Map();
	let seen = new Set();
	let opener = null;
	let restoreFocus = true;
	let pressedOnBackdrop = false;

	closeButton.addEventListener("click", safe(close));
	previous.addEventListener(
		"click",
		safe(() => turnPage(-1))
	);
	next.addEventListener(
		"click",
		safe(() => turnPage(1))
	);
	// "Open" and "View all" are links: a click with a modifier key or the middle button is left to the browser,
	// which opens a new tab; a plain click navigates in place.
	const onLinkClick = safe((event) => {
		const { button, ctrlKey, metaKey, shiftKey, altKey } = event;
		if (button !== 0 || ctrlKey || metaKey || shiftKey || altKey) return;
		event.preventDefault();
		navigate(event.currentTarget.getAttribute("href"));
	});
	viewAll.addEventListener("click", onLinkClick);
	overlay.addEventListener(
		"pointerdown",
		safe((event) => (pressedOnBackdrop = event.target === overlay))
	);
	overlay.addEventListener(
		"click",
		safe((event) => {
			if (event.target === overlay && pressedOnBackdrop) close();
		})
	);
	dialog.addEventListener("keydown", safe(onKeydown));

	store.subscribe(
		safe((state, previousState) => {
			if (state.ui.open !== previousState.ui.open) {
				if (state.ui.open) show();
				else hide();
			} else if (state.ui.open && state.summary !== previousState.summary) {
				onSummary();
			}
		})
	);

	function show() {
		opener = root.activeElement ?? document.activeElement;
		restoreFocus = true;
		selected = ALL_TAB;
		page = 0;
		loading = false;
		feeds = new Map();
		seen = new Set();
		overlay.hidden = false;
		renderTabs();
		tabs.focusSelected();
		load();
		refresh();
	}

	function hide() {
		generation++;
		overlay.hidden = true;
		if (restoreFocus && opener?.isConnected) opener.focus();
		opener = null;
	}

	function close() {
		store.set({ ui: { ...store.get().ui, open: false } });
	}

	// Opens a desk route after closing the window; focus then belongs to the page that opens.
	function navigate(route) {
		restoreFocus = false;
		close();
		frappe.set_route(routeArguments(route));
	}

	function onKeydown(event) {
		if (event.key === "Escape") {
			event.preventDefault();
			// The desk's own Escape handler would close a form dialog or grid row behind the window.
			event.stopPropagation();
			close();
		} else if (event.key === "Tab") {
			const focusable = [...dialog.querySelectorAll(FOCUSABLE)].filter(
				(candidate) => !candidate.closest("[hidden]")
			);
			const index = trapIndex(
				focusable.indexOf(root.activeElement),
				focusable.length,
				event.shiftKey
			);
			if (index >= 0) {
				event.preventDefault();
				focusable[index].focus();
			}
		}
	}

	// The selected tab, or "All" when the selected source is no longer in the summary.
	function currentTab(all = buildTabs(store.get().summary)) {
		return all.find((tab) => tab.id === selected) ?? all[0];
	}

	function renderTabs() {
		const all = buildTabs(store.get().summary);
		tabs.render(all, currentTab(all).id);
		panel.setAttribute("aria-labelledby", tabs.selectedElementId());
	}

	function select(id) {
		if (id === selected) return;
		selected = id;
		page = 0;
		renderTabs();
		load();
	}

	function turnPage(step) {
		if (loading) return;
		page += step;
		load();
	}

	// A new summary updates the counters; the selected tab is reloaded only when the sources it shows changed
	// (a source appeared or went away), or when it waited for the first summary.
	function onSummary() {
		const tab = currentTab();
		const changed = tab.id !== selected || feeds.get(tab.id)?.keys !== tab.sources.join("\n");
		selected = tab.id;
		renderTabs();
		// The focused tab may be gone with its source.
		keepFocusInside();
		if (changed) {
			page = 0;
			load();
		}
	}

	// Fetches the summary; with none to show, the window says so and offers to try again.
	function refresh() {
		return refreshSummary().then(
			safe(() => {
				if (!overlay.hidden && !store.get().summary) {
					showError(__("These items could not be loaded."), () => {
						showLoading();
						refresh();
					});
				}
			})
		);
	}

	function feedFor(tab) {
		const keys = tab.sources.join("\n");
		if (feeds.get(tab.id)?.keys !== keys) {
			feeds.set(tab.id, { keys, feed: createFeed(tab.sources, api.getItems, pageSize) });
		}
		return feeds.get(tab.id).feed;
	}

	function load() {
		safe(loadPage)();
	}

	async function loadPage() {
		const run = ++generation;
		showLoading();
		const summary = store.get().summary;
		// Before the first summary the tabs are not known; onSummary loads once it arrives.
		if (!summary) return;
		const tab = currentTab();
		const feed = feedFor(tab);
		loading = true;
		const result = await feed.page(page);
		if (run !== generation) return;
		loading = false;
		page = result.page;
		showResult(tab, feed, result, summary);
	}

	function showLoading() {
		panel.setAttribute("aria-busy", "true");
		toolbar.hidden = true;
		content.replaceChildren(state(null, __("Loading…", null, "Attention Center")));
		keepFocusInside();
	}

	function showError(message, retry) {
		panel.removeAttribute("aria-busy");
		content.replaceChildren(state(ICONS.alert, message, retry));
		pager.hidden = true;
		announce(message);
		keepFocusInside();
	}

	function showResult(tab, feed, { items, hasMore, failed }, summary) {
		const retry = () => {
			feed.retry();
			load();
		};
		toolbar.hidden = !tab.listRoute;
		if (tab.listRoute) viewAll.href = tab.listRoute;

		if (!items.length && failed.length) {
			showError(__("These items could not be loaded."), retry);
			return;
		}
		panel.removeAttribute("aria-busy");
		markSeen(tab.sources.filter((key) => !failed.includes(key)));
		if (items.length) showItems(tab, { items, hasMore, failed }, summary, retry);
		else showEmpty();
		keepFocusInside();
	}

	function showEmpty() {
		content.replaceChildren(
			state(ICONS.check, __("Nothing is waiting on you"), null, "empty")
		);
		pager.hidden = true;
		announce(__("Nothing is waiting on you"));
	}

	function showItems(tab, { items, hasMore, failed }, summary, retry) {
		const labels = new Map(summary.sources.map((source) => [source.key, source.label]));
		const parts = [];
		if (failed.length) {
			const names = frappe.utils.comma_and(failed.map((key) => labels.get(key)));
			parts.push(
				state(
					ICONS.alert,
					__("Some sources could not be loaded: {0}", [names]),
					retry,
					"notice"
				)
			);
		}
		parts.push(
			renderTable(items, {
				showSource: tab.id === ALL_TAB,
				sourceLabel: (key) => labels.get(key),
				format: FORMAT,
				onOpenClick: onLinkClick,
			})
		);
		content.replaceChildren(...parts);
		content.scrollTop = 0;

		pager.hidden = page === 0 && !hasMore;
		previous.disabled = page === 0;
		next.disabled = !hasMore;
		pageLabel.textContent = __("Page {0}", [page + 1], "Attention Center");
		announce(__("Page {0}. Items shown: {1}", [page + 1, items.length]));
	}

	// Viewing a tab marks its sources seen once per opening of the window [FR-API-03]; the summary that follows
	// clears their "new" markers.
	function markSeen(keys) {
		const unseen = keys.filter((key) => !seen.has(key));
		if (!unseen.length) return;
		for (const key of unseen) seen.add(key);
		Promise.all(unseen.map((key) => api.markSeen(key))).then(safe(refreshSummary), () => {});
	}

	// A button disabled or removed while it had focus drops focus out of the dialog; it goes back inside.
	function keepFocusInside() {
		if (!overlay.hidden && !root.activeElement) dialog.focus();
	}

	function state(icon, message, retry, kind = "state") {
		const box = element("div", kind);
		if (icon) box.insertAdjacentHTML("beforeend", icon);
		box.append(element("span", null, message));
		if (retry) {
			const button = textButton(__("Try again", null, "Attention Center"), "link-button");
			button.addEventListener("click", safe(retry));
			box.append(button);
		}
		return box;
	}
}

// Dates arrive as ISO text in the system time zone; Frappe's helpers show them in the user's zone and format.
const FORMAT = {
	age: (iso) => frappe.datetime.prettyDate(iso) || FORMAT.date(iso),
	date: (iso) => frappe.datetime.str_to_user(iso.replace("T", " ")),
};

function iconButton(icon, label) {
	const button = element("button", "icon-button");
	button.type = "button";
	button.innerHTML = icon;
	button.setAttribute("aria-label", label);
	button.title = label;
	return button;
}

function textButton(label, className = "pager-button") {
	const button = element("button", className, label);
	button.type = "button";
	return button;
}
