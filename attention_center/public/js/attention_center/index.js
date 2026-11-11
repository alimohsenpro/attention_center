import { coalesce } from "./alerts/coalesce.js";
import { newItemAlerts } from "./alerts/policy.js";
import { createApi, createTransport } from "./api.js";
import { startRefreshLoop } from "./realtime.js";
import { createStore } from "./store.js";
import { createLauncher } from "./ui/launcher.js";
import { STYLES } from "./ui/styles.js";
import { createToasts, newItemsText } from "./ui/toast.js";
import { badge } from "./util/badge.js";
import { adoptStyles } from "./util/dom.js";
import { createGuard } from "./util/guard.js";
import { watchTitle } from "./util/title.js";

const HOST_ID = "attention-center-root";
// dir and lang for layout and fonts, data-theme for the dark tokens (§7.1).
const MIRRORED_ATTRIBUTES = ["dir", "lang", "data-theme"];
const WINDOW_BUNDLE = "attention_center_window.bundle.js";
const SHORTCUT = "alt+shift+a";

const guard = createGuard();
const observe = (callback) => new MutationObserver(guard.safe(callback));

guard.run(() => {
	if (frappe.app instanceof frappe.Application) start();
	else $(document).one("app_ready", guard.safe(start));
});

function start() {
	const boot = frappe.boot.attention_center;
	if (!boot?.enabled || frappe.session.user === "Guest" || document.getElementById(HOST_ID)) {
		return;
	}

	const shadow = createHost();
	const api = createApi(createTransport(fetch, () => frappe.csrf_token));
	const store = createStore(
		{ summary: null, prefs: boot.preferences, ui: { open: false } },
		api.getSummary
	);
	const title = watchTitle(document, observe);
	guard.addCleanup(title.stop);
	const announce = createLiveRegion(shadow);
	const openWindow = windowOpener(shadow, {
		store,
		api,
		safe: guard.safe,
		announce,
		refreshSummary: () => store.refreshSummary(),
		pageSize: boot.settings.page_size,
	});
	const toggleWindow = guard.safe(() => {
		if (store.get().ui.open) setOpen(store, false);
		else openWindow();
	});
	const launcher = createLauncher(shadow, {
		onOpen: toggleWindow,
		onToggleCollapsed: guard.safe(() => toggleCollapsed(store, api)),
	});
	const toasts = createToasts(shadow, { onOpen: openWindow, safe: guard.safe, announce });
	frappe.ui.keys?.add_shortcut?.({
		shortcut: SHORTCUT,
		action: toggleWindow,
		description: __("Open or close the Attention Center"),
		ignore_inputs: true,
	});

	const render = guard.safe((state) => {
		const summaryBadge = badge(state.summary);
		launcher.render({
			badge: summaryBadge,
			collapsed: state.prefs.launcher_collapsed,
			open: state.ui.open,
		});
		title.set(summaryBadge.count);
	});
	store.subscribe(render);
	render(store.get());
	store.onSummary(
		guard.safe(
			alertOnNewItems(store, {
				launcher,
				toasts,
				coalesceSeconds: boot.settings.coalesce_seconds,
			})
		)
	);

	// The first summary is fetched after the boot, never during it [NFR-PERF-02].
	startRefreshLoop({
		refresh: store.refreshSummary,
		heartbeatSeconds: boot.settings.heartbeat_seconds,
		realtime: frappe.realtime,
		page: document,
		network: window,
		safe: guard.safe,
	});
}

function createHost() {
	const host = document.createElement("div");
	host.id = HOST_ID;
	mirrorPageAttributes(host);
	document.body.append(host);
	guard.addCleanup(() => host.remove());
	const shadow = host.attachShadow({ mode: "open" });
	adoptStyles(shadow, STYLES);
	return shadow;
}

function mirrorPageAttributes(host) {
	const page = document.documentElement;
	const copy = () => {
		for (const name of MIRRORED_ATTRIBUTES) {
			const value = page.getAttribute(name);
			if (value === null) host.removeAttribute(name);
			else host.setAttribute(name, value);
		}
	};
	copy();
	const observer = observe(copy);
	observer.observe(page, { attributes: true, attributeFilter: MIRRORED_ATTRIBUTES });
	guard.addCleanup(() => observer.disconnect());
}

// The polite live region through which the window and the alerts speak to screen readers [FR-UI-08].
function createLiveRegion(shadow) {
	const region = document.createElement("div");
	region.className = "visually-hidden";
	region.setAttribute("role", "status");
	region.setAttribute("aria-live", "polite");
	shadow.append(region);
	return (text) => {
		// A message equal to the last one changes nothing in the region and would not be spoken again.
		region.textContent = region.textContent === text ? `${text}\u00a0` : text;
	};
}

// Opens the window on a tab (null for "All"), loading its bundle on the first call [NFR-PERF-02]. The bundle
// is added as a <script> rather than through frappe.require, which freezes the desk while it loads and never
// unfreezes it when the request fails. A bundle that does not load is like a failed request: the next click
// tries again.
function windowOpener(shadow, options) {
	let ready = null;
	return (tab = null) => {
		ready ??= loadScript(frappe.boot.assets_json?.[WINDOW_BUNDLE]).then(
			guard.safe(() => window.attention_center_window.createWindow(shadow, options))
		);
		ready.then(
			guard.safe(() => setOpen(options.store, true, tab)),
			() => (ready = null)
		);
	};
}

function loadScript(src) {
	return new Promise((resolve, reject) => {
		if (!src) {
			reject(new Error(`${WINDOW_BUNDLE} is not built`));
			return;
		}
		const script = document.createElement("script");
		script.src = src;
		script.onload = () => {
			script.remove();
			resolve();
		};
		script.onerror = () => {
			script.remove();
			reject(new Error(`${src} did not load`));
		};
		document.head.append(script);
	});
}

// `tab` is the tab the window shows when it opens, or switches to when it is open already.
function setOpen(store, open, tab = null) {
	store.set({ ui: { ...store.get().ui, open, tab } });
}

// Pulses the launcher and shows one toast per burst when a summary brings new items (§7.4); the alert policy
// decides which items count, alerts/coalesce.js merges a burst.
function alertOnNewItems(store, { launcher, toasts, coalesceSeconds }) {
	let burst = null;
	return ({ previous, summary, actor }) => {
		const alerts = newItemAlerts({
			previous,
			summary,
			actor,
			user: frappe.session.user,
			prefs: store.get().prefs,
			now: frappe.datetime.system_datetime(),
		});
		if (!alerts.length) return;
		launcher.pulse();
		const result = coalesce(burst, alerts, Date.now(), coalesceSeconds * 1000);
		burst = result.burst;
		if (!result.toast) return;
		const { id, count, level, sticky, source } = result.toast;
		const label = summary.sources.find((candidate) => candidate.key === source)?.label;
		toasts.show({ id, level, sticky, tab: source, text: newItemsText(count, label) });
	};
}

function toggleCollapsed(store, api) {
	const prefs = {
		...store.get().prefs,
		launcher_collapsed: !store.get().prefs.launcher_collapsed,
	};
	store.set({ prefs });
	// The launcher follows the click at once; if storing it fails, the next page load shows the stored state.
	api.setPreferences({ launcher_collapsed: prefs.launcher_collapsed }).catch(() => {});
}
