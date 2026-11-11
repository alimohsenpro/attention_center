import { dndActive } from "./policy.js";

// The gestures after which the browser lets the page play sound [FR-SND-03]. pointerup rather than pointerdown:
// a touch grants that permission only when it ends.
const UNLOCK_EVENTS = ["pointerup", "keydown"];

// The sound engine [FR-SND-01..04, §7.5]: plays the tone of a role (`standard`, `urgent`, `immediate` or
// `reminder`) in one tab of the browser.
//
// Nothing plays while `User.mute_sounds` is set (`muted`) or Do Not Disturb lasts, whatever the role: both come
// before the sound scope, which the alert policy has applied already. Nothing plays at volume 0 either. When the
// browser refuses to play before the user's first gesture, `onLocked(first)` is told (`first` the first time in
// the page load, for the one-time hint), the tab leaves the next alerts to other tabs, and the next pointerup or
// keydown unlocks it, without a reload, by playing a muted tone; then `onUnlocked()` is told.
//
// `tones` are the boot's tones ({id, url}); `settings` name the organisation's urgent, immediate and reminder
// tones; `getPrefs()` returns the user's tone, volume (0–100) and dnd_until; `now()` the current time as naive
// ISO text in the system time zone, the form of dnd_until; `claim(id)` resolves true in the one tab that plays
// alert `id` (alerts/tabs.js); `page` (the window) receives the gestures; `safe` wraps the handlers in the
// client's guard.
export function createSound({
	tones,
	settings,
	getPrefs,
	muted,
	now,
	claim,
	page,
	safe,
	onLocked,
	onUnlocked,
	createAudio = (url) => new Audio(url),
}) {
	// One audio element per tone, created on its first play.
	const players = new Map();
	let locked = false;
	let hinted = false;

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

	// Browsers play a muted tone at any time, and an audible one once the page had a gesture they count. A gesture
	// they do not count (Escape) unlocks nothing: the next sound is refused and locks the tab again.
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

	// Plays the tone of `role` for alert `id`, unless something above keeps it silent or another tab plays it.
	// A sound the browser refuses is no failure of the client: the promise resolves all the same.
	async function play(role, id) {
		const prefs = getPrefs();
		if (muted || dndActive(prefs.dnd_until, now()) || !prefs.volume || locked) return;
		if (!(await claim(id))) return;
		const audio = player(role, prefs);
		audio.volume = prefs.volume / 100;
		audio.currentTime = 0;
		try {
			await audio.play();
		} catch (error) {
			if (error?.name === "NotAllowedError") lock();
		}
	}

	return { play };
}
