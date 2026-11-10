// Inline SVG on a 20 px grid: Frappe's sprite references do not resolve inside a shadow tree (§7.1).
const svg = (body) =>
	`<svg viewBox="0 0 20 20" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${body}</svg>`;

export const ICONS = {
	bell: svg(
		'<path d="M5 8a5 5 0 0 1 10 0v2.5c0 1.2.5 2.3 1.5 3.25v.25h-13v-.25C4.5 12.8 5 11.7 5 10.5Z"/><path d="M8.25 16.75a1.9 1.9 0 0 0 3.5 0"/>'
	),
	// Points to the inline end in left-to-right text; the stylesheet mirrors it.
	chevron: svg('<path d="m8 5 5 5-5 5"/>'),
};
