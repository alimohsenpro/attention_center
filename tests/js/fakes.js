import { readFileSync } from "node:fs";

import { createSound } from "../../attention_center/public/js/attention_center/alerts/sound.js";
import { createTabs } from "../../attention_center/public/js/attention_center/alerts/tabs.js";

// Test doubles for the browser's tabs: a clock the test moves by hand, localStorage, BroadcastChannel and audio
// elements, and a browser whose tabs run the sound engine on them.

// The timers due within a step run in the order of their time, then of their creation.
export function fakeClock() {
	let time = 0;
	let nextId = 1;
	const timers = new Map();
	return {
		now: () => time,
		setTimeout(callback, ms) {
			timers.set(nextId, { at: time + ms, callback });
			return nextId++;
		},
		clearTimeout: (id) => timers.delete(id),
		advance(ms) {
			const end = time + ms;
			for (;;) {
				let due = null;
				for (const [id, timer] of timers) {
					if (timer.at <= end && (!due || timer.at < due.at)) due = { id, ...timer };
				}
				if (!due) break;
				timers.delete(due.id);
				time = due.at;
				due.callback();
			}
			time = end;
		},
	};
}

// The localStorage of one browser: call the result once per tab. A tab reads its own writes at once and those of
// another tab `latencyMs` later; once every write has arrived, the latest write of a key stands in every tab.
export function fakeStorage(clock, latencyMs = 0) {
	const writes = [];
	return () => {
		const visible = (write) => write.tab === tab || write.at + latencyMs <= clock.now();
		const current = (key) =>
			writes.filter((write) => write.key === key && visible(write)).at(-1)?.value ?? null;
		const keys = () => [...new Set(writes.map((write) => write.key))].filter(current);
		const tab = {
			get length() {
				return keys().length;
			},
			key: (index) => keys()[index] ?? null,
			getItem: current,
			setItem: (key, value) =>
				writes.push({ key, value: String(value), at: clock.now(), tab }),
			removeItem: (key) => writes.push({ key, value: null, at: clock.now(), tab }),
		};
		return tab;
	};
}

// BroadcastChannel of one name: call the result once per tab. A message reaches every other tab `latencyMs`
// later, never the tab that posted it.
export function fakeBroadcast(clock, latencyMs = 1) {
	const channels = [];
	return () => {
		const channel = new EventTarget();
		channel.postMessage = (data) => {
			for (const other of channels.filter((candidate) => candidate !== channel)) {
				clock.setTimeout(
					() => other.dispatchEvent(Object.assign(new Event("message"), { data })),
					latencyMs
				);
			}
		};
		channels.push(channel);
		return channel;
	};
}

// The tones as the boot sends them: those of tones.json, with their URL.
export const TONES = JSON.parse(
	readFileSync(new URL("../../attention_center/public/sounds/tones.json", import.meta.url))
).map((tone) => ({ ...tone, url: `/assets/attention_center/sounds/${tone.file}` }));
export const SETTINGS = {
	urgent_tone: "urgent",
	immediate_tone: "immediate",
	reminder_tone: "reminder",
};
// The current time as the engine reads it, naive ISO text in the system time zone.
export const NOW = "2026-11-11 09:00:00";
export const PREFS = { tone: "knock", volume: 60, dnd_until: null };

export const toneUrl = (id) => TONES.find((tone) => tone.id === id).url;

// A browser whose tabs share a clock, localStorage and BroadcastChannel, and each run the sound engine.
export function fakeBrowser({ storageLatencyMs = 0, channelLatencyMs = 1 } = {}) {
	const clock = fakeClock();
	const storage = fakeStorage(clock, storageLatencyMs);
	const channel = fakeBroadcast(clock, channelLatencyMs);
	let opened = 0;
	return {
		clock,
		// Opens a tab: the visibility of its document, the value random() gives its claims, the user's
		// preferences, the organisation's tones and User.mute_sounds.
		open({
			visibility = "visible",
			random = 0.5,
			prefs = {},
			settings = SETTINGS,
			muted = false,
		} = {}) {
			const tab = {
				id: `tab-${++opened}`,
				prefs: { ...PREFS, ...prefs },
				// The error an audible play() is refused with (NotAllowedError until a gesture), or null.
				refusal: null,
				// The error a muted play() is refused with, or null.
				mutedRefusal: null,
				// {url, volume} of every sound the tab played audibly.
				played: [],
				// The `first` flag of every onLocked call, and the number of onUnlocked calls.
				locks: [],
				unlocks: 0,
				// The window, which receives the gestures.
				page: new EventTarget(),
				storage: storage(),
			};
			const tabs = createTabs({
				channel: channel(),
				storage: tab.storage,
				page: { visibilityState: visibility },
				safe: (fn) => fn,
				clock,
				random: () => random,
				tab: tab.id,
			});
			tab.mark = tabs.mark;
			tab.sound = createSound({
				tones: TONES,
				settings,
				getPrefs: () => tab.prefs,
				muted,
				now: () => NOW,
				claim: tabs.claim,
				page: tab.page,
				safe: (fn) => fn,
				onLocked: (first) => tab.locks.push(first),
				onUnlocked: () => tab.unlocks++,
				createAudio: (url) => fakeAudio(url, tab),
			});
			return tab;
		},
		// Starts the plays, lets the tabs' timers run for `ms` and waits until every play has ended.
		async play(plays, ms = 1000) {
			const started = plays.map(([tab, role, id]) => tab.sound.play(role, id));
			clock.advance(ms);
			await Promise.all(started);
		},
	};
}

// HTMLAudioElement as the engine uses it. A play() is refused with the tab's refusal, as a browser refuses an
// audible one until the page had a gesture.
function fakeAudio(url, tab) {
	return {
		volume: 1,
		muted: false,
		currentTime: 0,
		play() {
			const refusal = this.muted ? tab.mutedRefusal : tab.refusal;
			if (refusal) return Promise.reject(new DOMException("play() was refused", refusal));
			if (!this.muted) tab.played.push({ url, volume: this.volume });
			return Promise.resolve();
		},
		pause() {},
	};
}

// Lets every pending promise callback run.
export const settle = () => new Promise((resolve) => setImmediate(resolve));
