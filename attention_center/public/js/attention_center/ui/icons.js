// Inline SVG on a 20 px grid: Frappe's sprite references do not resolve inside a shadow tree (§7.1).
const svg = (body) =>
	`<svg viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;

export const ICONS = {
	bell: svg(
		'<path d="M5 8a5 5 0 0 1 10 0v2.5c0 1.2.5 2.3 1.5 3.25v.25h-13v-.25C4.5 12.8 5 11.7 5 10.5Z"/><path d="M8.25 16.75a1.9 1.9 0 0 0 3.5 0"/>'
	),
	// Points to the inline end in left-to-right text; the stylesheet mirrors it.
	chevron: svg('<path d="m8 5 5 5-5 5"/>'),
	x: svg('<path d="m5 5 10 10M15 5 5 15"/>'),
	// A speaker with a cross: the browser keeps the sound off.
	soundOff: svg(
		'<path d="M3.75 7.5h2.5L10 4.5v11l-3.75-3h-2.5Z"/><path d="m13 8 4 4m0-4-4 4"/>'
	),
	volume: svg(
		'<path d="M3.75 7.5h2.5L10 4.5v11l-3.75-3h-2.5Z"/><path d="M13 7.5a3.5 3.5 0 0 1 0 5M15.25 5.25a6.75 6.75 0 0 1 0 9.5"/>'
	),
	settings: svg(
		'<path d="M3.5 6h8.25M15.75 6h.75M3.5 14h.75M8.25 14h8.25"/><circle cx="13.75" cy="6" r="2"/><circle cx="6.25" cy="14" r="2"/>'
	),
	clock: svg('<circle cx="10" cy="10" r="7.25"/><path d="M10 6.25V10l2.5 1.75"/>'),
	check: svg('<circle cx="10" cy="10" r="7.25"/><path d="m6.75 10.25 2.25 2.25 4.25-4.5"/>'),
	alert: svg(
		'<path d="M8.7 3.5a1.5 1.5 0 0 1 2.6 0l6 10.5a1.5 1.5 0 0 1-1.3 2.25H4a1.5 1.5 0 0 1-1.3-2.25Z"/><path d="M10 8v3M10 13.75v.01"/>'
	),
	// The display modes: a screen with the window in its middle, in its bottom corner or along its side. The
	// panel and the drawer are drawn at the inline end in left-to-right text; the stylesheet mirrors them.
	dialog: svg(
		'<rect x="2.75" y="3.75" width="14.5" height="12.5" rx="2"/><rect x="6.5" y="7.25" width="7" height="5.5" rx="1"/>'
	),
	panel: svg(
		'<rect x="2.75" y="3.75" width="14.5" height="12.5" rx="2"/><rect x="10" y="7.5" width="4.25" height="5.75" rx="1"/>'
	),
	drawer: svg(
		'<rect x="2.75" y="3.75" width="14.5" height="12.5" rx="2"/><path d="M11.75 3.75v12.5"/>'
	),
	// Points to the inline end in left-to-right text; the stylesheet mirrors it.
	external: svg(
		'<path d="M11 4h5v5M16 4l-7 7M14 12v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h3"/>'
	),
};
