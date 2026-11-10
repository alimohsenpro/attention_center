import { createApi, createTransport } from "./api.js";
import { createStore } from "./store.js";
import { createLauncher } from "./ui/launcher.js";
import { createPlaceholder } from "./ui/placeholder.js";
import { STYLES } from "./ui/styles.js";
import { badge } from "./util/badge.js";
import { createGuard } from "./util/guard.js";
import { watchTitle } from "./util/title.js";

const HOST_ID = "attention-center-root";
// dir and lang for layout and fonts, data-theme for the dark tokens (§7.1).
const MIRRORED_ATTRIBUTES = ["dir", "lang", "data-theme"];
// The desk's own requests after boot go first; no request of this app delays the boot [NFR-PERF-02].
const FIRST_FETCH_DELAY_MS = 1000;

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
	const store = createStore({ summary: null, prefs: boot.preferences, ui: { open: false } });
	const api = createApi(createTransport(fetch, () => frappe.csrf_token));
	const title = watchTitle(document, observe);
	guard.addCleanup(title.stop);
	const launcher = createLauncher(shadow, {
		onOpen: guard.safe(() =>
			store.set({ ui: { ...store.get().ui, open: !store.get().ui.open } })
		),
		onToggleCollapsed: guard.safe(() => toggleCollapsed(store, api)),
	});
	const placeholder = createPlaceholder(shadow);

	const render = guard.safe((state) => {
		const summaryBadge = badge(state.summary);
		launcher.render({
			badge: summaryBadge,
			collapsed: state.prefs.launcher_collapsed,
			open: state.ui.open,
		});
		title.set(summaryBadge.count);
		placeholder.render(state);
	});
	store.subscribe(render);
	render(store.get());

	setTimeout(
		guard.safe(() => refreshSummary(store, api)),
		FIRST_FETCH_DELAY_MS
	);
}

function createHost() {
	const host = document.createElement("div");
	host.id = HOST_ID;
	mirrorPageAttributes(host);
	document.body.append(host);
	guard.addCleanup(() => host.remove());
	const shadow = host.attachShadow({ mode: "open" });
	adoptStyles(shadow);
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

function adoptStyles(shadow) {
	if ("adoptedStyleSheets" in shadow && "replaceSync" in CSSStyleSheet.prototype) {
		const sheet = new CSSStyleSheet();
		sheet.replaceSync(STYLES);
		shadow.adoptedStyleSheets = [sheet];
	} else {
		const style = document.createElement("style");
		style.textContent = STYLES;
		shadow.append(style);
	}
}

async function refreshSummary(store, api) {
	let summary;
	try {
		summary = await api.getSummary();
	} catch {
		// A failed request is not a failure of the client: the launcher keeps what it shows.
		return;
	}
	store.set({ summary });
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
