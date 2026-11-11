// Do Not Disturb times [FR-SND-02]. No DOM and no frappe, so they can be tested with node --test. Times are naive
// "YYYY-MM-DD HH:mm:ss" text of one time zone, the form Frappe's date helpers give; the arithmetic reads them as UTC,
// so that the browser's own time zone plays no part.

const HOUR_MS = 3600 * 1000;
const DAY_MS = 24 * HOUR_MS;

// The Do Not Disturb choices of the settings view, in the order shown.
export const DND_CHOICES = ["off", "hour", "day"];

// When a Do Not Disturb chosen at `now` ends: an hour later, or at the midnight that ends `now`'s day; null for "off".
export function dndUntil(choice, now) {
	if (choice === "hour") return format(parse(now) + HOUR_MS);
	if (choice === "day") return format(parse(`${now.slice(0, 10)} 00:00:00`) + DAY_MS);
	return null;
}

// The choice that describes a Do Not Disturb ending at `until`, in the time zone of `now`: "off" when there is
// none or it has ended, "day" when it ends at the midnight that ends `now`'s day, else "hour".
export function dndChoice(until, now) {
	if (!until || parse(until) <= parse(now)) return "off";
	return parse(until) === parse(dndUntil("day", now)) ? "day" : "hour";
}

// How long until `until` from `now`, in milliseconds; both in one time zone.
export function msUntil(until, now) {
	return parse(until) - parse(now);
}

// Takes either separator between the date and the time: the server sends "T", Frappe's helpers a space.
function parse(text) {
	return Date.parse(`${text.replace(" ", "T")}Z`);
}

function format(ms) {
	return new Date(ms).toISOString().slice(0, 19).replace("T", " ");
}
