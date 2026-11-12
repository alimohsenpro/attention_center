import { ANNOUNCEMENTS } from "../util/announcements.js";
import { displayMode, nextDisplayMode } from "../util/display_mode.js";
import { adoptStyles, element, textButton } from "../util/dom.js";
import { createFeed } from "../util/feed.js";
import { keepsKey, trapIndex } from "../util/keys.js";
import { routeArguments } from "../util/route.js";
import { createPreferenceEditor } from "../util/settings.js";
import { ALL_TAB, buildTabs, itemFetcher } from "../util/window_tabs.js";
import { createAnnouncement } from "./announcement.js";
import { ICONS } from "./icons.js";
import { createSettings, modeLabel } from "./settings.js";
import { createSnooze } from "./snooze.js";
import { renderTable } from "./table.js";
import { createTabs } from "./tabs.js";
import { WINDOW_STYLES } from "./window_styles.js";

const PANEL_ID = "ac-panel";
const TITLE_ID = "ac-window-title";
const SUMMARY_ID = "ac-window-summary";
// Inactive tabs (tabindex -1) are left out: Tab reaches the tab list through its selected tab only, and a group of
// radio buttons through its checked one.
const FOCUSABLE =
	":is(button, input:not([type='radio']:not(:checked)), select, a[href], [tabindex]):not([disabled], [tabindex='-1'])";

// The window [FR-UI-02, FR-UI-03, FR-UI-08]: one tab per source and the "All" tab, the items of the selected tab
// page by page, and loading, empty and error states, in the container of the display_mode preference. It
// opens and closes with `store.ui.open`, on the tab `store.ui.tab` names ("All" when none), and follows
// `store.prefs.display_mode` while open. When it opens by itself at login, `store.ui.newSince` holds the count of
// its "new since you last looked" line [FR-ALERT-05]. The settings button in its header shows the user's settings
// in place of the items (ui/settings.js) [FR-SET-02]; "Open" on an announcement shows it there too, with its
// acknowledgement (ui/announcement.js) [FR-ANN-02, FR-ANN-03].
//
// The dialog is modal: a backdrop covers the page and focus stays inside. The panel above the launcher and
// the drawer on the inline-end edge leave the page usable, so focus may leave them. Closing returns focus to
// the element that had it before opening, unless the user has moved it onto the page meanwhile.
//
// Each item has "Remind me later" beside "Open" (ui/snooze.js) [FR-SNZ-01].
//
// `api` has getItems, getAnnouncementsToAcknowledge, getAnnouncement, acknowledgeAnnouncement, markSeen,
// remindMeLater and setPreferences; `safe` wraps every handler in the client's guard;
// `announce(text)` speaks through the polite live region; `refreshSummary()` fetches the summary into the store;
// `tones`, `muted` and `previewTone(id)` serve the settings view.
export function createWindow(
	root,
	{ store, api, safe, announce, refreshSummary, pageSize, tones, muted, previewTone }
) {
	adoptStyles(root, WINDOW_STYLES);
	const frame = element("div", "frame");
	frame.hidden = true;
	const dialog = element("section", "window");
	dialog.tabIndex = -1;
	dialog.setAttribute("role", "dialog");
	dialog.setAttribute("aria-labelledby", TITLE_ID);

	const header = element("header", "window-header");
	const title = element("h2", "window-title", __("What needs your attention"));
	title.id = TITLE_ID;
	const settingsButton = iconButton(ICONS.settings, __("Settings", null, "Attention Center"));
	settingsButton.setAttribute("aria-pressed", "false");
	// Its icon and label name the mode it switches to (applyMode).
	const modeButton = element("button", "icon-button mode-button");
	modeButton.type = "button";
	const closeButton = iconButton(ICONS.x, __("Close", null, "Attention Center"));
	const actions = element("div", "window-actions");
	actions.append(settingsButton, modeButton, closeButton);
	header.append(title, actions);
	const summaryStrip = element("p", "summary-strip");
	summaryStrip.id = SUMMARY_ID;
	summaryStrip.hidden = true;
	dialog.append(header, summaryStrip);

	// The tabs and their panel, which the settings view replaces while it shows.
	const itemsView = element("div", "items-view");
	const tabs = createTabs(itemsView, { panelId: PANEL_ID, safe, onSelect: select });
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
	itemsView.append(panel);
	dialog.append(itemsView);

	const editor = createPreferenceEditor({
		getPrefs: () => store.get().prefs,
		setPrefs: (prefs) => store.set({ prefs }),
		write: api.setPreferences,
		onStatus: (status) => settings.showStatus(status),
	});
	const settings = createSettings(dialog, {
		store,
		editor,
		tones,
		muted,
		preview: previewTone,
		onBack: backToList,
		safe,
		announce,
	});
	const announcement = createAnnouncement(dialog, {
		api,
		format: FORMAT,
		onBack: backToList,
		// Every page fetched may show the announcement as awaiting: going back fetches them again.
		onAcknowledged: () => {
			feeds = new Map();
			refreshSummary();
		},
		safe,
		announce,
	});
	frame.append(dialog);
	root.append(frame);

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
	let mode;
	applyMode();

	settingsButton.addEventListener(
		"click",
		safe(() => (settings.shown ? returnToItems() : showView("settings")))
	);
	modeButton.addEventListener("click", safe(switchMode));
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
	viewAll.addEventListener(
		"click",
		safe((event) => {
			if (!isPlainClick(event)) return;
			event.preventDefault();
			navigate(viewAll.getAttribute("href"));
		})
	);
	// An announcement opens in the window, where it can be acknowledged; its link still opens its form in a new tab.
	const onOpenClick = safe((event, { source, item }) => {
		if (!isPlainClick(event)) return;
		event.preventDefault();
		if (source === ANNOUNCEMENTS) {
			showView("announcement");
			announcement.show(item.id);
		} else {
			navigate(item.route);
		}
	});
	// Only the dialog's frame has a box of its own, the backdrop; the panel's and the drawer's take no clicks.
	frame.addEventListener(
		"pointerdown",
		safe((event) => (pressedOnBackdrop = event.target === frame))
	);
	frame.addEventListener(
		"click",
		safe((event) => {
			if (event.target === frame && pressedOnBackdrop) close();
		})
	);
	dialog.addEventListener("keydown", safe(onKeydown));

	store.subscribe(
		safe((state, previousState) => {
			if (state.prefs.display_mode !== previousState.prefs.display_mode) applyMode();
			if (state.ui.open !== previousState.ui.open) {
				if (state.ui.open) show();
				else hide();
			} else if (state.ui.open && state.ui !== previousState.ui) {
				// Asked to open while open, as from a toast's "View": the user asks for what arrived.
				showSummary(state.ui.newSince);
				showTab(state.ui.tab);
			} else if (state.ui.open && state.summary !== previousState.summary) {
				onSummary();
			}
		})
	);

	function show() {
		opener = root.activeElement ?? document.activeElement;
		restoreFocus = true;
		frame.hidden = false;
		showSummary(store.get().ui.newSince);
		showTab(store.get().ui.tab);
		refresh();
	}

	// The "new since you last looked" line, for a count; none for null. The count was read before the window
	// opened, since opening it marks the sources seen.
	function showSummary(newSince) {
		const shown = typeof newSince === "number";
		summaryStrip.hidden = !shown;
		if (!shown) {
			dialog.removeAttribute("aria-describedby");
			return;
		}
		summaryStrip.innerHTML = ICONS.bell;
		summaryStrip.append(element("span", null, newSinceText(newSince)));
		dialog.setAttribute("aria-describedby", SUMMARY_ID);
	}

	// Shows a tab ("All" for null) from its first page with items fetched afresh, and marks its sources seen
	// again: the pages and seen marks of this opening may predate what the user now asks to see.
	function showTab(id) {
		showView("items");
		selected = id ?? ALL_TAB;
		page = 0;
		loading = false;
		feeds = new Map();
		seen = new Set();
		renderTabs();
		tabs.focusSelected();
		load();
	}

	function hide() {
		generation++;
		// Focus the user moved onto the page beside a panel or drawer stays where they put it.
		const returnFocus = restoreFocus && ownsFocus();
		frame.hidden = true;
		if (returnFocus && opener?.isConnected) opener.focus();
		opener = null;
	}

	function close() {
		store.set({ ui: { ...store.get().ui, open: false } });
	}

	// Puts the window in the container of the display_mode preference; content, tab and page stay as they are.
	function applyMode() {
		mode = displayMode(store.get().prefs.display_mode);
		frame.dataset.mode = mode.toLowerCase();
		if (mode === "Dialog") dialog.setAttribute("aria-modal", "true");
		else dialog.removeAttribute("aria-modal");
		const next = nextDisplayMode(mode);
		const label = modeLabel(next);
		modeButton.innerHTML = ICONS[next.toLowerCase()];
		modeButton.setAttribute("aria-label", label);
		modeButton.title = label;
	}

	function switchMode() {
		editor.change({ display_mode: nextDisplayMode(mode) });
	}

	// Back from the settings or an announcement to the items: the page is drawn again, from the pages already
	// fetched, and marks its sources seen if it was answered meanwhile.
	function returnToItems() {
		showView("items");
		load();
	}

	function backToList() {
		returnToItems();
		tabs.focusSelected();
	}

	// Shows the tabs and their items, the settings, or an announcement.
	function showView(view) {
		settingsButton.setAttribute("aria-pressed", String(view === "settings"));
		itemsView.hidden = view !== "items";
		if (view === "settings") settings.show();
		else settings.hide();
		if (view !== "announcement") announcement.hide();
	}

	// Opens a desk route after closing the window; focus then belongs to the page that opens.
	function navigate(route) {
		restoreFocus = false;
		close();
		frappe.set_route(routeArguments(route));
	}

	function onKeydown(event) {
		if (keepsKey(event.key)) event.stopPropagation();
		if (event.key === "Escape") {
			event.preventDefault();
			close();
		} else if (event.key === "Tab" && mode === "Dialog") {
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
		// The focused tab may be gone with its source.
		keepingFocus(renderTabs);
		if (changed) {
			page = 0;
			load();
		}
	}

	// Fetches the summary; with none to show, the window says so and offers to try again.
	function refresh() {
		return refreshSummary().then(
			safe(() => {
				if (!frame.hidden && !store.get().summary) {
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
			feeds.set(tab.id, {
				keys,
				feed: createFeed(tab.sources, itemFetcher(tab, api), pageSize),
			});
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
		keepingFocus(() => {
			panel.setAttribute("aria-busy", "true");
			toolbar.hidden = true;
			content.replaceChildren(state(null, __("Loading…", null, "Attention Center")));
		});
	}

	function showError(message, retry) {
		keepingFocus(() => {
			panel.removeAttribute("aria-busy");
			content.replaceChildren(state(ICONS.alert, message, retry));
			pager.hidden = true;
		});
		announce(message);
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
		// Behind the settings or an announcement the items are not seen yet; returnToItems draws them again.
		if (!itemsView.hidden) markSeen(tab.marks.filter((key) => !failed.includes(key)));
		keepingFocus(() => {
			panel.removeAttribute("aria-busy");
			if (items.length) showItems(tab, { items, hasMore, failed }, summary, retry);
			else showEmpty();
		});
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
				onOpenClick,
				snooze: (item, columns) =>
					createSnooze(item, {
						columns,
						remind: api.remindMeLater,
						format: FORMAT,
						safe,
						announce,
					}),
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

	// Whether focus belongs in the window: always in the modal dialog; beside a panel or drawer only while the
	// user keeps it there.
	function ownsFocus() {
		return mode === "Dialog" || dialog.contains(root.activeElement);
	}

	// Runs a change of the window's content. A control it removes or disables while it has focus would drop
	// focus onto the page; the window takes it instead.
	function keepingFocus(change) {
		const owned = ownsFocus();
		change();
		if (owned && !frame.hidden && !root.activeElement) dialog.focus();
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

// The line of the window that opened by itself at login: how many action items arrived since the user last
// looked. It shows with none too, so that the user knows the items waiting are ones they have seen.
export function newSinceText(count) {
	if (!count) return __("Nothing new since you last looked");
	if (count === 1) return __("1 new item since you last looked");
	return __("{0} new items since you last looked", [count]);
}

// Dates arrive as ISO text in the system time zone; Frappe's helpers show them in the user's zone and format.
const FORMAT = {
	age: (iso) => frappe.datetime.prettyDate(iso) || FORMAT.date(iso),
	date: (iso) => frappe.datetime.str_to_user(iso.replace("T", " ")),
};

// A click the window handles itself; one with a modifier key or another button is left to the browser, which opens
// the link in a new tab.
function isPlainClick({ button, ctrlKey, metaKey, shiftKey, altKey }) {
	return button === 0 && !ctrlKey && !metaKey && !shiftKey && !altKey;
}

function iconButton(icon, label) {
	const button = element("button", "icon-button");
	button.type = "button";
	button.innerHTML = icon;
	button.setAttribute("aria-label", label);
	button.title = label;
	return button;
}
