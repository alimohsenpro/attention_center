import { DISPLAY_MODES, displayMode } from "../util/display_mode.js";
import { element, textButton } from "../util/dom.js";
import { SOUND_SCOPES } from "../util/settings.js";
import { DND_CHOICES, dndChoice, dndUntil, msUntil } from "../util/time.js";
import { ICONS } from "./icons.js";

const TONE_ID = "ac-settings-tone";
const VOLUME_ID = "ac-settings-volume";

// The window's settings view [FR-SND-02, FR-SET-02, FR-UI-03]: the sound scope, the tone with a preview, the volume,
// Do Not Disturb, auto-open after login and the display mode. Each control shows the effective preference from the
// store and changes it through `editor` (util/settings.js), which applies it at once and stores it; the view follows
// the store, so a change made in another tab shows too. It has no control for the launcher's counter or for the
// marks of urgent, immediate and overdue items (D-06).
//
// Do Not Disturb is chosen in the user's time zone, so that "until the end of the day" ends at their midnight, and
// stored in the system time zone, like every time the client compares (§7.4).
//
// `tones` are the boot's tones, of which the user picks a standard one; `muted` is User.mute_sounds; `preview(id)`
// plays a tone (alerts/sound.js); `onBack()` returns to the items; `safe` wraps every handler and timer in the
// client's guard; `announce(text)` speaks through the polite live region.
export function createSettings(
	parent,
	{ store, editor, tones, muted, preview, onBack, safe, announce }
) {
	const view = element("div", "settings");
	view.hidden = true;

	const top = element("div", "settings-top");
	const title = element("h3", "settings-title", __("Your settings"));
	const back = textButton(__("Back to the list"), "link-button");
	back.addEventListener("click", safe(onBack));
	top.append(title, back);
	const status = element("p", "settings-status");

	const scopeLabels = {
		"Urgent Only": __("Urgent and immediate items only"),
		"Action Items": __("Items that need your action"),
		Everything: __("Everything, information included"),
	};
	const scope = radioGroup(
		"scope",
		__("Play a sound for"),
		SOUND_SCOPES.map((value) => [value, scopeLabels[value]]),
		(sound_scope) => editor.change({ sound_scope })
	);
	scope.fieldset.append(
		element(
			"p",
			"hint",
			__("Urgent and immediate items play their own tone, whatever you choose.")
		)
	);

	const tone = document.createElement("select");
	tone.id = TONE_ID;
	tone.className = "settings-select";
	for (const { id, label } of tones.filter((candidate) => candidate.role === "standard")) {
		const option = element("option", null, label);
		option.value = id;
		tone.append(option);
	}
	tone.addEventListener(
		"change",
		safe(() => editor.change({ tone: tone.value }))
	);
	const previewButton = textButton(
		__("Preview", null, "Attention Center"),
		"pager-button preview-button"
	);
	previewButton.insertAdjacentHTML("afterbegin", ICONS.volume);
	previewButton.addEventListener(
		"click",
		safe(() => preview(tone.value))
	);

	const volume = document.createElement("input");
	volume.type = "range";
	volume.id = VOLUME_ID;
	volume.className = "settings-range";
	volume.min = "0";
	volume.max = "100";
	const volumeText = element("output", "settings-output");
	volumeText.setAttribute("for", VOLUME_ID);
	// Dragging shows the value; the change applies and is stored when the user lets go.
	volume.addEventListener(
		"input",
		safe(() => showVolume(volume.valueAsNumber))
	);
	volume.addEventListener(
		"change",
		safe(() => editor.change({ volume: volume.valueAsNumber }))
	);

	const dndLabels = {
		off: __("Off", null, "Attention Center"),
		hour: __("For 1 hour"),
		day: __("Until the end of the day"),
	};
	const dnd = radioGroup(
		"dnd",
		__("Do Not Disturb", null, "Attention Center"),
		DND_CHOICES.map((choice) => [choice, dndLabels[choice]]),
		(choice) => editor.change({ dnd_until: systemUntil(choice) })
	);
	const dndStatus = element("p", "hint");
	dnd.fieldset.append(dndStatus);

	const mutedNote = element(
		"p",
		"settings-note",
		__("Sounds are muted in your user settings, so none will play.")
	);
	mutedNote.hidden = !muted;

	const autoOpen = document.createElement("input");
	autoOpen.type = "checkbox";
	autoOpen.addEventListener(
		"change",
		safe(() => editor.change({ auto_open_on_login: autoOpen.checked }))
	);
	const autoOpenChoice = element("label", "choice settings-field");
	autoOpenChoice.append(
		autoOpen,
		element("span", null, __("Open this window by itself after login when items wait for you"))
	);

	const mode = radioGroup(
		"mode",
		__("How the window shows"),
		DISPLAY_MODES.map((value) => [value, modeLabel(value)]),
		(display_mode) => editor.change({ display_mode })
	);

	view.append(
		top,
		status,
		group(
			__("Sound", null, "Attention Center"),
			scope.fieldset,
			field(__("Tone", null, "Attention Center"), TONE_ID, tone, previewButton),
			field(__("Volume", null, "Attention Center"), VOLUME_ID, volume, volumeText),
			dnd.fieldset,
			mutedNote
		),
		group(__("Window", null, "Attention Center"), autoOpenChoice, mode.fieldset),
		element(
			"p",
			"hint",
			__("The counter and the marks of urgent, immediate and overdue items always show.")
		)
	);
	parent.append(view);

	// Redraws the view when Do Not Disturb ends while it is shown.
	let dndTimer = null;

	store.subscribe(
		safe((state, previous) => {
			if (!view.hidden && state.prefs !== previous.prefs) render();
		})
	);

	function render() {
		const { prefs } = store.get();
		scope.check(prefs.sound_scope);
		tone.value = prefs.tone;
		volume.value = String(prefs.volume);
		showVolume(prefs.volume);

		const now = frappe.datetime.now_datetime();
		const until = prefs.dnd_until && frappe.datetime.convert_to_user_tz(prefs.dnd_until);
		const choice = dndChoice(until, now);
		dnd.check(choice);
		dndStatus.textContent = dndText(choice, until);
		clearTimeout(dndTimer);
		// A second late, so that the time read then is past the end.
		if (choice !== "off") dndTimer = setTimeout(safe(render), msUntil(until, now) + 1000);

		autoOpen.checked = prefs.auto_open_on_login;
		mode.check(displayMode(prefs.display_mode));
		previewButton.disabled = muted || choice !== "off" || !prefs.volume;
	}

	function showVolume(value) {
		const text = __("{0}%", [value]);
		volumeText.textContent = text;
		volume.setAttribute("aria-valuetext", text);
	}

	// The state of the writes (util/settings.js). Focus on "Try again", which goes away, moves to "Back to the list".
	function showStatus(state) {
		const hadFocus = status.contains(parent.getRootNode().activeElement);
		status.replaceChildren();
		if (state === "saving") status.textContent = __("Saving…", null, "Attention Center");
		if (state === "saved") status.textContent = __("Saved", null, "Attention Center");
		if (state === "failed") {
			const message = __("Your change could not be saved.");
			const retry = textButton(__("Try again", null, "Attention Center"), "link-button");
			retry.addEventListener(
				"click",
				safe(() => editor.retry())
			);
			status.append(element("span", null, message), retry);
			announce(message);
		}
		if (hadFocus && !view.hidden) back.focus();
	}

	function radioGroup(name, legend, choices, onChoose) {
		const fieldset = element("fieldset", "settings-field");
		fieldset.append(element("legend", "settings-label", legend));
		const inputs = choices.map(([value, label]) => {
			const input = document.createElement("input");
			input.type = "radio";
			input.name = `ac-${name}`;
			input.value = value;
			input.addEventListener(
				"change",
				safe(() => onChoose(value))
			);
			const choice = element("label", "choice");
			choice.append(input, element("span", null, label));
			fieldset.append(choice);
			return input;
		});
		return {
			fieldset,
			check(value) {
				for (const input of inputs) input.checked = input.value === value;
			},
		};
	}

	return {
		get shown() {
			return !view.hidden;
		},
		show() {
			render();
			view.hidden = false;
		},
		hide() {
			view.hidden = true;
			clearTimeout(dndTimer);
		},
		showStatus,
	};
}

// The label of a display mode: the mode button names the mode it switches to, the settings view each choice.
export function modeLabel(mode) {
	if (mode === "Panel") return __("Show as a panel");
	if (mode === "Drawer") return __("Show as a drawer");
	return __("Show as a dialog");
}

// The end of a Do Not Disturb chosen now, in the system time zone; null for "off".
function systemUntil(choice) {
	const until = dndUntil(choice, frappe.datetime.now_datetime());
	return until && frappe.datetime.convert_to_system_tz(until);
}

// `until` is in the user's time zone, as "YYYY-MM-DD HH:mm:ss".
function dndText(choice, until) {
	if (choice === "day") return __("Sounds are off until the end of the day. Alerts still show.");
	if (choice === "hour") {
		const time = frappe.datetime.str_to_user(until.slice(11), true);
		return __("Sounds are off until {0}. Alerts still show.", [time]);
	}
	return __("Turns every sound off for a while. Alerts still show.");
}

function group(heading, ...children) {
	const section = element("section", "settings-group");
	section.append(element("h4", "settings-heading", heading), ...children);
	return section;
}

function field(label, id, ...controls) {
	const box = element("div", "settings-field");
	const caption = element("label", "settings-label", label);
	caption.htmlFor = id;
	const row = element("div", "settings-row");
	row.append(...controls);
	box.append(caption, row);
	return box;
}
