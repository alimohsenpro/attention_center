import { coalesce } from "./alerts/coalesce.js";
import { autoOpenOnLogin } from "./alerts/login.js";
import { newItemAlerts } from "./alerts/policy.js";
import { startReminder } from "./alerts/reminder.js";
import { createSound } from "./alerts/sound.js";
import { alertId, CHANNEL_NAME, createTabs } from "./alerts/tabs.js";
import { createApi, createTransport } from "./api.js";
import { startRefreshLoop } from "./realtime.js";
import { createStore } from "./store.js";
import { createLauncher } from "./ui/launcher.js";
import { STYLES } from "./ui/styles.js";
import { createToasts, newItemsText } from "./ui/toast.js";
import {
	ANNOUNCEMENTS,
	toastUnseenImmediate,
	withAnnouncementPriority,
} from "./util/announcements.js";
import { badge } from "./util/badge.js";
import { hideStandardBell } from "./util/bell.js";
import { adoptStyles } from "./util/dom.js";
import { createGuard } from "./util/guard.js";
import { sharePreferences } from "./util/share_prefs.js";
import { watchTitle } from "./util/title.js";

const HOST_ID = "attention-center-root";
// dir and lang for layout and fonts, data-theme for the dark tokens (§7.1).
const MIRRORED_ATTRIBUTES = ["dir", "lang", "data-theme"];
const WINDOW_BUNDLE = "attention_center_window.bundle.js";
const SHORTCUT = "alt+shift+a";
// The toast id of the hint that the browser blocks the sound.
const SOUND_HINT = "sound-hint";
// The toast id of the periodic reminder.
const REMINDER_TOAST = "reminder";
// The toast id of the immediate announcements not seen yet, raised when the page loads.
const UNSEEN_ANNOUNCEMENTS_TOAST = "unseen-announcements";

const guard = createGuard();
const observe = (callback) => new MutationObserver(guard.safe(callback));

guard.run(() => {
	hideBellIfSet(frappe.boot.attention_center);
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
	const channel = new BroadcastChannel(CHANNEL_NAME);
	guard.addCleanup(() => channel.close());
	sharePreferences({ store, channel, user: frappe.session.user, safe: guard.safe });
	const title = watchTitle(document, observe);
	guard.addCleanup(title.stop);
	const announce = createLiveRegion(shadow);
	const muted = Boolean(frappe.boot.user.mute_sounds);
	const openWindow = windowOpener(shadow, {
		store,
		api,
		safe: guard.safe,
		announce,
		refreshSummary: () => store.refreshSummary(),
		pageSize: boot.settings.page_size,
		tones: boot.tones,
		muted,
		// The sound engine exists by the time the user can press "Preview".
		previewTone: (id) => sound.preview(id),
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
	const sound = createAlertSound(boot, { store, launcher, toasts, channel, muted });
	const reminder = startReminder({
		intervalHours: boot.settings.reminder_interval_hours,
		store,
		storage: localStorage,
		page: document,
		systemNow: () => frappe.datetime.system_datetime(),
		remind: guard.safe(remindOfAttention({ toasts, sound })),
		safe: guard.safe,
	});
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
				api,
				launcher,
				toasts,
				sound,
				coalesceSeconds: boot.settings.coalesce_seconds,
			})
		)
	);
	store.onSummary(
		guard.safe(
			toastUnseenImmediate({
				fetchUnseen: api.getUnseenAnnouncements,
				show: (count) => showUnseenAnnouncements(store, toasts, count),
			})
		)
	);
	store.onSummary(
		guard.safe(
			autoOpenOnLogin({
				shouldAutoOpen: boot.should_auto_open,
				store,
				open: (newSince) => openWindow(null, newSince),
				onOpened: () => {
					reminder.restart();
					// If recording it fails, the next page load of this login session opens the window again.
					api.noteAutoOpened().catch(() => {});
				},
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

// Before the desk draws its navbar, so that the bell never shows [FR-SET-01]. A failure of the client shows it again:
// the launcher that stands in for it is gone then.
function hideBellIfSet(boot) {
	if (boot?.enabled && boot.settings.hide_standard_bell)
		guard.addCleanup(hideStandardBell(document));
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

// Opens the window on a tab (null for "All"), loading its bundle on the first call [NFR-PERF-02], and resolves
// whether it opened. `newSince` is the "new since you last looked" count the window shows when it opens by
// itself at login. The bundle is added as a <script> rather than through frappe.require, which freezes the desk
// while it loads and never unfreezes it when the request fails. A bundle that does not load is like a failed
// request: the next click tries again.
function windowOpener(shadow, options) {
	let ready = null;
	return (tab = null, newSince = null) => {
		ready ??= loadScript(frappe.boot.assets_json?.[WINDOW_BUNDLE]).then(
			guard.safe(() => window.attention_center_window.createWindow(shadow, options))
		);
		return ready.then(
			guard.safe(() => {
				setOpen(options.store, true, tab, newSince);
				return true;
			}),
			() => {
				ready = null;
				return false;
			}
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

// The alerts' sound (§7.5), played by one tab of the browser. A tab the browser keeps silent until a gesture pulses
// the launcher and, the first time, shows a hint until the gesture comes [FR-SND-03].
function createAlertSound(boot, { store, launcher, toasts, channel, muted }) {
	const tabs = createTabs({ channel, storage: localStorage, page: document, safe: guard.safe });
	const sound = createSound({
		tones: boot.tones,
		settings: boot.settings,
		getPrefs: () => store.get().prefs,
		muted,
		now: () => frappe.datetime.system_datetime(),
		claim: tabs.claim,
		mark: tabs.mark,
		release: tabs.release,
		page: window,
		safe: guard.safe,
		onLocked: (first) => {
			launcher.pulse();
			if (first) {
				toasts.notice(
					SOUND_HINT,
					__(
						"Your browser blocked the alert sound. Click anywhere on the page to turn sound on."
					)
				);
			}
		},
		onUnlocked: () => toasts.dismiss(SOUND_HINT),
	});
	return sound;
}

// `tab` is the tab the window shows when it opens, or switches to when it is open already; `newSince` the count
// of its "new since you last looked" line, null for none.
function setOpen(store, open, tab = null, newSince = null) {
	store.set({ ui: { ...store.get().ui, open, tab, newSince } });
}

// Pulses the launcher, and shows one toast and plays one sound per burst, when a summary brings new items (§7.4,
// §7.5); the alert policy decides which items count, an announcement's alert takes the priority of the
// announcements that arrived (util/announcements.js), alerts/coalesce.js merges a burst, and of the browser's tabs
// one plays the sound.
function alertOnNewItems(store, { api, launcher, toasts, sound, coalesceSeconds }) {
	let burst = null;
	// The alerts of each summary are shown in the order of the summaries, although some wait for the announcements.
	let ready = Promise.resolve();
	return ({ previous, summary, actor }) => {
		const context = { prefs: store.get().prefs, now: frappe.datetime.system_datetime() };
		const alerts = newItemAlerts({
			previous,
			summary,
			actor,
			user: frappe.session.user,
			...context,
		});
		if (!alerts.length) return;
		launcher.pulse();
		const decided = ready.then(() =>
			withAnnouncementPriority(alerts, previous, api.getItems, context)
		);
		ready = decided.catch(() => {});
		return decided.then((final) => {
			const result = coalesce(burst, final, Date.now(), coalesceSeconds * 1000);
			burst = result.burst;
			if (result.toast) {
				const { id, count, level, sticky, source } = result.toast;
				const label = summary.sources.find((candidate) => candidate.key === source)?.label;
				toasts.show({ id, level, sticky, tab: source, text: newItemsText(count, label) });
			}
			return sound.alert(result.sound, alertId(final, summary));
		});
	};
}

// The sticky toast, raised when the page loads, of the announcements the user has not seen yet when an immediate one
// is among them (§7.4). No tone: it tells of no arrival, and would sound at every page load until the user looks.
function showUnseenAnnouncements(store, toasts, count) {
	const label = store
		.get()
		.summary.sources.find((source) => source.key === ANNOUNCEMENTS)?.label;
	toasts.show({
		id: UNSEEN_ANNOUNCEMENTS_TOAST,
		level: "immediate",
		sticky: true,
		tab: ANNOUNCEMENTS,
		text: newItemsText(count, label),
	});
}

// Shows the periodic reminder (§7.4): a toast, which opens the window only when the user clicks it, and the
// reminder tone in one tab of the browser unless Do Not Disturb keeps it silent. Its text names no number:
// totals.attention may count an item that is both urgent and overdue twice (§5).
function remindOfAttention({ toasts, sound }) {
	return ({ id, level, sticky, sound: role }) => {
		toasts.show({
			id: REMINDER_TOAST,
			level,
			sticky,
			tab: null,
			text: __("Reminder: urgent or overdue items are still waiting for you"),
		});
		return role ? sound.alert(role, id) : undefined;
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
