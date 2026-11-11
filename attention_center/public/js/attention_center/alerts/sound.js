import { dndActive } from "./policy.js";

// The gestures after which the browser lets the page play sound [FR-SND-03]. pointerup rather than pointerdown:
// a touch grants that permission only when it ends.
const UNLOCK_EVENTS = ["pointerup", "keydown"];

// The sound engine [FR-SND-01..04, §7.5]: plays the tone of a role (`standard`, `urgent`, `immediate` or
// `reminder`) in one tab of the browser.
//
// Nothing plays while `User.mute_sounds` is set (`muted`) or Do Not Disturb lasts, whatever the role: both come
// before the sound scope, which the alert policy has applied already. Nothing plays at volume 0 either. A tab that
// has not shown yet that the browser lets it play (no gesture since the page loaded, no sound played) leaves an
// alert to the tabs that have, and plays it only when none of them claims it. When the browser refuses to play
// before the user's first gesture, `onLocked(first)` is told (`first` the first time in the page load, for the
// one-time hint), the tab gives the alert back and leaves the next alerts to other tabs, and the next pointerup or
// keydown unlocks it, without a reload, by playing a muted tone; then `onUnlocked()` is told.
//
// `tones` are the boot's tones ({id, url}); `settings` name the organisation's urgent, immediate and reminder
// tones; `getPrefs()` returns the user's tone, volume (0–100) and dnd_until; `now()` the current time as naive
// ISO text in the system time zone, the form of dnd_until; `claim(id, proven)` resolves true in the one tab that
// plays alert `id`, `mark(id)` records it as handled without playing it and `release(id)` gives back a claim
// the browser refused (alerts/tabs.js); `page` (the window) receives the gestures; `activation`
// (navigator.userActivation) tells whether the page had a gesture the browser counts; `safe` wraps the handlers
// in the client's guard.
export function createSound({
	tones,
	settings,
	getPrefs,
	muted,
	now,
	claim,
	mark,
	release,
	page,
	safe,
	onLocked,
	onUnlocked,
	activation = navigator.userActivation,
	createAudio = (url) => new Audio(url),
}) {
	// One audio element per tone, created on its first play.
	const players = new Map();
	let locked = false;
	let played = false;
	// Whether the tab has shown that the browser lets it play: a gesture the browser counts, or a sound it played.
	const proven = () => played || Boolean(activation?.hasBeenActive);
	// A hint the toast stack has no room for (three immediate toasts) is not tried again: those toasts leave only
	// by a click or a key, which unlocks the sound.
	let hinted = false;
	// Whether the last sound of the tab's burst was heard: played here, or claimed by another tab, which plays it.
	let burstHeard = false;

	function player(role, prefs) {
		const id = {
			standard: prefs.tone,
			urgent: settings.urgent_tone,
			immediate: settings.immediate_tone,
			reminder: settings.reminder_tone,
		}[role];
		if (!players.has(id)) {
			players.set(id, createAudio(tones.find((tone) => tone.id === id).url));
		}
		return players.get(id);
	}

	function listen() {
		for (const type of UNLOCK_EVENTS) page.addEventListener(type, unlock, { capture: true });
	}

	function lock() {
		locked = true;
		onLocked(!hinted);
		hinted = true;
		listen();
	}

	// An audible tone plays once the page had a gesture the browser counts. Some browsers play a muted one at any
	// time, others (Chromium) refuse it too until then. After a gesture they do not count (Escape), the muted tone
	// is therefore either refused, and the tab waits for the next gesture, or played, and the next sound is refused
	// and locks the tab again.
	const unlock = safe(() => {
		for (const type of UNLOCK_EVENTS) {
			page.removeEventListener(type, unlock, { capture: true });
		}
		const audio = player("standard", getPrefs());
		audio.muted = true;
		return audio.play().then(
			() => {
				audio.pause();
				audio.muted = false;
				locked = false;
				onUnlocked();
			},
			() => {
				audio.muted = false;
				listen();
			}
		);
	});

	// Sounds the alerts of a summary, `id` being their alertId (alerts/tabs.js) [§7.4]. With a `role` it plays
	// that role's tone, unless something above keeps it silent or another tab plays it. A null `role` means the
	// tab's burst already sounded (alerts/coalesce.js): nothing plays, and the alerts are marked as handled so that
	// a tab that fetches the same change later stays silent too, but only when the burst was heard. A tab whose
	// burst was silent (muted, Do Not Disturb, volume 0, locked or refused) leaves them to another tab, which
	// plays them.
	// A sound the browser refuses is no failure of the client: the promise resolves all the same.
	async function alert(role, id) {
		if (!role) {
			if (id && burstHeard) mark(id);
			return;
		}
		const prefs = getPrefs();
		burstHeard =
			!muted && !dndActive(prefs.dnd_until, now()) && Boolean(prefs.volume) && !locked;
		if (!burstHeard || !(await claim(id, proven()))) return;
		const audio = player(role, prefs);
		audio.volume = prefs.volume / 100;
		audio.currentTime = 0;
		try {
			await audio.play();
			played = true;
		} catch (error) {
			if (error?.name === "NotAllowedError") {
				burstHeard = false;
				release(id);
				lock();
			}
		}
	}

	return { alert };
}
