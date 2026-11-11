import assert from "node:assert/strict";
import test from "node:test";

import { STYLES } from "../../attention_center/public/js/attention_center/ui/styles.js";

// WCAG 2.1 AA for text below 18.66 px bold or 24 px [NFR-A11Y-01]; the client's largest text is 16 px.
const AA_TEXT = 4.5;
const DARK = ':host([data-theme="dark"])';

// Text colours on the backgrounds ui/styles.js and ui/window_styles.js put them on: [text, background, where].
// Names are tokens without "--ac-"; "white" is the #ffffff the stylesheets use on dark and coloured fills. Links
// (--ac-link) are green 700 in the light theme and green 500 in the dark one.
const BOTH = [
	["ink", "surface", "window, toasts, rows, pager buttons, selects"],
	["ink", "surface-2", "summary strip, settings note, tab counters, hovered rows, retry in a notice"],
	["muted", "surface", "tabs, metadata, page label, loading and empty states, hints"],
	["muted", "surface-2", "table header, error notice, metadata of a hovered row"],
	["gold-soft", "green-800", "launcher label"],
	["gold-soft", "green-900", "hovered launcher label"],
	["white", "green-800", "window title, start of the header"],
	["white", "green-900", "window title, end of the header"],
	["green-900", "gold", "launcher counter"],
	["green-900", "p-urgent", "urgent pills"],
	["white", "p-immediate", "counters with attention items, immediate and overdue pills"],
];
const PAIRS = {
	light: [
		...BOTH,
		["green-700", "surface", "links, active tab, Open, View all, toast action"],
		["surface", "green-700", "hovered Open and toast action"],
		["p-immediate", "surface", "age of an overdue row"],
		["p-immediate", "surface-2", "age of a hovered overdue row"],
	],
	dark: [
		...BOTH,
		["green-500", "surface", "links, active tab, Open, View all, toast action"],
		["surface", "green-500", "hovered Open and toast action"],
		["p-very", "surface", "age of an overdue row"],
		["p-very", "surface-2", "age of a hovered overdue row"],
	],
};

// The tokens of a theme as the shadow host declares them: the light ones, with the dark theme's on top.
function tokens(theme) {
	const values = { white: "#ffffff" };
	for (const [, selector, body] of STYLES.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
		const name = selector.trim();
		if (name !== ":host" && !(theme === "dark" && name === DARK)) continue;
		for (const [, token, value] of body.matchAll(/--ac-([\w-]+):\s*(#[0-9a-f]{6});/gi)) {
			values[token] = value;
		}
	}
	return values;
}

// WCAG 2.1 relative luminance and contrast ratio.
function luminance(hex) {
	const [r, g, b] = [1, 3, 5].map((start) => {
		const channel = parseInt(hex.slice(start, start + 2), 16) / 255;
		return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(foreground, background) {
	const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
	return (light + 0.05) / (dark + 0.05);
}

test("the contrast ratio follows WCAG 2.1", () => {
	assert.equal(contrast("#000000", "#ffffff"), 21);
	assert.equal(contrast("#ffffff", "#ffffff"), 1);
	assert.equal(contrast("#767676", "#ffffff").toFixed(2), "4.54");
});

test("the host declares the tokens of docs/DESIGN_TOKENS.md for both themes", () => {
	assert.equal(tokens("light").surface, "#ffffff");
	assert.equal(tokens("dark").surface, "#18201f");
	assert.equal(tokens("dark")["green-700"], "#067564");
});

for (const theme of Object.keys(PAIRS)) {
	const palette = tokens(theme);
	for (const [text, background, where] of PAIRS[theme]) {
		test(`${theme}: ${text} on ${background} (${where})`, (t) => {
			assert.ok(palette[text] && palette[background], "both are tokens of ui/styles.js");
			const ratio = contrast(palette[text], palette[background]);
			t.diagnostic(`${ratio.toFixed(2)}:1`);
			assert.ok(ratio >= AA_TEXT, `${ratio.toFixed(2)}:1 is below ${AA_TEXT}:1`);
		});
	}
}
