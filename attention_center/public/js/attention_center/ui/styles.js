// The shadow root's only stylesheet. The tokens of docs/DESIGN_TOKENS.md live on the host, where a site can
// override them from outside; logical properties only, so that RTL and LTR share one sheet (§7.1).
export const STYLES = `
:host {
	all: initial !important;
	display: block !important;
	font-family: inherit !important;
	--ac-green-900: #03302b;
	--ac-green-800: #044640;
	--ac-green-700: #067564;
	--ac-green-500: #0e9f86;
	--ac-gold: #c59a42;
	--ac-gold-soft: #f1d99a;
	--ac-surface: #ffffff;
	--ac-surface-2: #f5f8f7;
	--ac-ink: #17302c;
	--ac-muted: #63756f;
	--ac-border: #e3ebe8;
	--ac-track: #edf2f0;
	--ac-shadow: 0 10px 28px -16px rgba(0, 0, 0, 0.35);
	--ac-p-immediate: #c0392b;
	--ac-p-very: #e0703a;
	--ac-p-urgent: #c59a42;
	--ac-p-normal: #0e9f86;
	--ac-radius-sm: 8px;
	--ac-radius: 12px;
	--ac-radius-lg: 18px;
}

:host([data-theme="dark"]) {
	--ac-surface: #18201f;
	--ac-surface-2: #1f2a28;
	--ac-ink: #e8f0ee;
	--ac-muted: #9db0aa;
	--ac-border: #2c3a37;
	--ac-track: #2a3633;
	--ac-shadow: 0 10px 28px -16px rgba(0, 0, 0, 0.6);
}

*,
*::before,
*::after {
	box-sizing: border-box;
}

[hidden] {
	display: none !important;
}

button {
	margin: 0;
	font: inherit;
	color: inherit;
}

:focus-visible {
	outline: 2px solid var(--ac-gold);
	outline-offset: 2px;
}

.visually-hidden,
.launcher[data-collapsed] .launcher-label {
	position: absolute;
	inline-size: 1px;
	block-size: 1px;
	overflow: hidden;
	clip-path: inset(50%);
	white-space: nowrap;
}

.launcher {
	position: fixed;
	inset-block-end: 16px;
	inset-inline-end: 16px;
	z-index: 1020;
	display: flex;
	align-items: center;
	gap: 8px;
	line-height: 1.6;
}

.launcher-main {
	position: relative;
	display: inline-flex;
	align-items: center;
	gap: 8px;
	block-size: 44px;
	padding-block: 0;
	padding-inline: 12px 16px;
	border: 0;
	border-radius: 999px;
	background: var(--ac-green-800);
	color: var(--ac-gold-soft);
	box-shadow: var(--ac-shadow);
	font-size: 14px;
	font-weight: 600;
	cursor: pointer;
	transition: background-color 150ms ease-out;
}

.launcher-main:hover {
	background: var(--ac-green-900);
}

.launcher-icon {
	position: relative;
	display: inline-flex;
}

.launcher-dot {
	position: absolute;
	inset-block-start: -2px;
	inset-inline-end: -2px;
	inline-size: 8px;
	block-size: 8px;
	border-radius: 999px;
	background: var(--ac-gold);
	box-shadow: 0 0 0 2px var(--ac-green-800);
}

.launcher-count {
	min-inline-size: 22px;
	padding-inline: 6px;
	border-radius: 999px;
	background: var(--ac-gold);
	color: var(--ac-green-900);
	font-size: 12px;
	font-weight: 700;
	line-height: 22px;
	text-align: center;
	font-variant-numeric: tabular-nums;
}

.launcher[data-attention] .launcher-count {
	background: var(--ac-p-immediate);
	color: #ffffff;
}

.launcher[data-collapsed] .launcher-main {
	inline-size: 44px;
	padding: 0;
	justify-content: center;
}

.launcher[data-collapsed] .launcher-count {
	position: absolute;
	inset-block-start: -6px;
	inset-inline-end: -6px;
}

.launcher-toggle {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	inline-size: 28px;
	block-size: 28px;
	padding: 0;
	border: 1px solid var(--ac-border);
	border-radius: 999px;
	background: var(--ac-surface);
	color: var(--ac-muted);
	box-shadow: var(--ac-shadow);
	cursor: pointer;
	transition: color 150ms ease-out;
}

.launcher-toggle:hover {
	color: var(--ac-ink);
}

.launcher-toggle svg {
	inline-size: 16px;
	block-size: 16px;
}

.launcher[data-collapsed] .launcher-toggle svg,
:host([dir="rtl"]) .launcher-toggle svg {
	transform: scaleX(-1);
}

:host([dir="rtl"]) .launcher[data-collapsed] .launcher-toggle svg {
	transform: none;
}

.placeholder {
	position: fixed;
	inset-block-end: 72px;
	inset-inline-end: 16px;
	z-index: 1020;
	inline-size: min(320px, calc(100vw - 32px));
	padding: 16px;
	border: 1px solid var(--ac-border);
	border-radius: var(--ac-radius-lg);
	background: var(--ac-surface);
	color: var(--ac-ink);
	box-shadow: var(--ac-shadow);
	font-size: 14px;
	line-height: 1.6;
}

.placeholder h2 {
	margin-block: 0 8px;
	margin-inline: 0;
	font-size: 16px;
	font-weight: 700;
}

.placeholder ul {
	margin: 0;
	padding: 0;
	list-style: none;
}

.placeholder li {
	display: flex;
	justify-content: space-between;
	gap: 12px;
	padding-block: 8px;
	border-block-start: 1px solid var(--ac-border);
	font-size: 13px;
}

.placeholder li > :last-child {
	font-weight: 700;
	font-variant-numeric: tabular-nums;
}

@media (prefers-reduced-motion: reduce) {
	*,
	*::before,
	*::after {
		transition: none !important;
		animation: none !important;
	}
}
`;
