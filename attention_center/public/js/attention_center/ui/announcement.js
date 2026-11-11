import { element, textButton } from "../util/dom.js";
import { ICONS } from "./icons.js";

const TITLE_ID = "ac-announcement-title";

// The window's view of one announcement [FR-ANN-02, FR-ANN-03]: its title, priority, sender, date and end, its body,
// and the acknowledgement it may ask for, given with one click. It takes the place of the tabs and their items, like
// the settings view, until "Back to the list".
//
// The body is the announcement's rich text, sanitised by the server when it was saved and again when it is read
// [NFR-SEC-03]: it is the one text the client sets as HTML. Its links open in a new browser tab, so that the desk and
// the window stay.
//
// `api` has getAnnouncement and acknowledgeAnnouncement; `format` has age(iso) and date(iso); `onBack()` returns to
// the items; `onAcknowledged()` follows a stored acknowledgement; `safe` wraps every handler in the client's guard;
// `announce(text)` speaks through the polite live region.
export function createAnnouncement(
	parent,
	{ api, format, onBack, onAcknowledged, safe, announce }
) {
	// Focus moves here when the view opens, since the "Open" link that had it is hidden with the items.
	const view = element("article", "announcement");
	view.hidden = true;
	view.tabIndex = -1;
	view.setAttribute("aria-labelledby", TITLE_ID);
	parent.append(view);
	// The name of the announcement shown; an answer for another one is not drawn.
	let shown = null;

	async function load(name) {
		view.replaceChildren(top(__("Loading…", null, "Attention Center")));
		let detail;
		try {
			detail = await api.getAnnouncement(name);
		} catch {
			if (shown === name) showError(name);
			return;
		}
		if (shown === name) render(detail);
	}

	function top(title) {
		const box = element("div", "announcement-top");
		const heading = element("h3", "announcement-title", title);
		heading.id = TITLE_ID;
		const back = textButton(__("Back to the list"), "link-button");
		back.addEventListener("click", safe(onBack));
		box.append(heading, back);
		return box;
	}

	function showError(name) {
		const message = __("This announcement could not be loaded.");
		const box = element("div", "state");
		box.insertAdjacentHTML("beforeend", ICONS.alert);
		box.append(element("span", null, message));
		const retry = textButton(__("Try again", null, "Attention Center"), "link-button");
		retry.addEventListener(
			"click",
			safe(() => load(name))
		);
		box.append(retry);
		view.replaceChildren(top(""), box);
		announce(message);
	}

	function render(detail) {
		const parts = [top(detail.title), meta(detail)];
		if (detail.body) {
			const body = element("div", "announcement-body");
			body.innerHTML = detail.body;
			for (const link of body.querySelectorAll("a[href]")) {
				link.target = "_blank";
				link.rel = "noopener noreferrer";
			}
			parts.push(body);
		}
		if (detail.requires_acknowledgement) parts.push(acknowledgement(detail));
		view.replaceChildren(...parts);
	}

	function meta(detail) {
		const line = element("p", "announcement-meta");
		if (detail.priority === "immediate" || detail.priority === "urgent") {
			const pill = element("span", "pill");
			pill.dataset.kind = detail.priority;
			pill.innerHTML = ICONS.alert;
			pill.append(element("span", null, priorityLabel(detail.priority)));
			line.append(pill);
		}
		if (detail.from_label)
			line.append(element("span", null, __("From {0}", [detail.from_label])));
		if (detail.date) {
			const time = element("time", null, format.age(detail.date));
			time.dateTime = detail.date;
			time.title = format.date(detail.date);
			line.append(time);
		}
		if (detail.valid_to) {
			const until = format.date(detail.valid_to);
			line.append(element("span", null, __("Shown until {0}", [until])));
		}
		return line;
	}

	function acknowledgement(detail) {
		const box = element("div", "acknowledgement");
		if (detail.acknowledged_at) {
			box.dataset.done = "";
			box.insertAdjacentHTML("beforeend", ICONS.check);
			box.append(element("span", null, acknowledgedText(detail.acknowledged_at, format)));
			return box;
		}
		const hint = element(
			"p",
			"hint",
			__("The sender asks you to confirm that you have read this announcement.")
		);
		const button = textButton(__("Acknowledge"), "primary-button");
		const status = element("p", "hint");
		let pending = false;
		// Not disabled while it is stored: a disabled button would drop the focus it has.
		button.addEventListener(
			"click",
			safe(async () => {
				if (pending) return;
				pending = true;
				button.setAttribute("aria-disabled", "true");
				status.textContent = __("Saving…", null, "Attention Center");
				let answer;
				try {
					answer = await api.acknowledgeAnnouncement(detail.name);
				} catch {
					pending = false;
					button.removeAttribute("aria-disabled");
					status.textContent = __("Your acknowledgement could not be saved. Try again.");
					announce(status.textContent);
					return;
				}
				if (shown === detail.name) {
					const hadFocus = view.contains(view.getRootNode().activeElement);
					render({ ...detail, acknowledged_at: answer.acknowledged_at });
					if (hadFocus) view.focus();
					announce(acknowledgedText(answer.acknowledged_at, format));
				}
				onAcknowledged();
			})
		);
		box.append(hint, button, status);
		return box;
	}

	return {
		show(name) {
			shown = name;
			view.hidden = false;
			view.focus();
			safe(load)(name);
		},
		hide() {
			shown = null;
			view.hidden = true;
			view.replaceChildren();
		},
	};
}

// The line of an announcement the user acknowledged, with the date and time in their format.
function acknowledgedText(iso, format) {
	return __("You acknowledged this announcement on {0}.", [format.date(iso)]);
}

function priorityLabel(priority) {
	return priority === "immediate"
		? __("Immediate", null, "Attention Center")
		: __("Urgent", null, "Attention Center");
}
