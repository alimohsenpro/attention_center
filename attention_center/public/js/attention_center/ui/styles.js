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

/* The counter badge takes the inline-end corner of the collapsed circle. */
.launcher[data-collapsed] .launcher-dot {
	inset-inline-end: auto;
	inset-inline-start: -2px;
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

/* One gold ring on new items; the reduced-motion rule below turns it off. */
.launcher[data-pulse] .launcher-main {
	animation: ac-pulse 1200ms ease-out;
}

@keyframes ac-pulse {
	from {
		box-shadow: var(--ac-shadow), 0 0 0 0 rgba(197, 154, 66, 0.8);
	}
	to {
		box-shadow: var(--ac-shadow), 0 0 0 12px rgba(197, 154, 66, 0);
	}
}

/* Toasts stack above the launcher (its 16 px offset, its 44 px height and a 12 px gap), the newest nearest to
   it. The stack itself takes no clicks, so the page between toasts stays usable. It sits over the open window
   (1030), whose dialog backdrop or panel would otherwise hide a toast and take its click, and below the desk's
   modals (1040/1050). */
.toasts {
	position: fixed;
	inset-block-end: 72px;
	inset-inline-end: 16px;
	z-index: 1035;
	display: flex;
	flex-direction: column;
	gap: 8px;
	inline-size: min(360px, calc(100vw - 32px));
	pointer-events: none;
}

.toast {
	--ac-toast-accent: var(--ac-p-normal);
	--ac-link: var(--ac-green-700);
	display: flex;
	align-items: center;
	gap: 8px;
	padding-block: 8px;
	padding-inline: 12px 4px;
	border: 1px solid var(--ac-border);
	border-inline-start: 3px solid var(--ac-toast-accent);
	border-radius: var(--ac-radius);
	background: var(--ac-surface);
	color: var(--ac-ink);
	box-shadow: var(--ac-shadow);
	font-size: 14px;
	line-height: 1.6;
	cursor: pointer;
	pointer-events: auto;
	animation: ac-toast-in 180ms ease-out;
}

.toast[data-level="urgent"] {
	--ac-toast-accent: var(--ac-p-urgent);
}

.toast[data-level="immediate"] {
	--ac-toast-accent: var(--ac-p-immediate);
}

/* The periodic reminder is about urgent, immediate and overdue items. */
.toast[data-level="reminder"] {
	--ac-toast-accent: var(--ac-p-urgent);
}

/* Green 700 is too dark on the dark surface for text (WCAG AA); green 500 is the same hue, lighter. */
:host([data-theme="dark"]) .toast {
	--ac-link: var(--ac-green-500);
}

.toast-icon {
	display: inline-flex;
	flex: none;
	color: var(--ac-toast-accent);
}

.toast-text {
	flex: 1;
	min-inline-size: 0;
	overflow-wrap: anywhere;
}

.toast-pill {
	display: inline-flex;
	margin-inline-end: 6px;
	padding-inline: 8px;
	border-radius: 999px;
	font-size: 12px;
	font-weight: 600;
}

.toast[data-level="urgent"] .toast-pill {
	background: var(--ac-p-urgent);
	color: var(--ac-green-900);
}

.toast[data-level="immediate"] .toast-pill {
	background: var(--ac-p-immediate);
	color: #ffffff;
}

.toast-action {
	flex: none;
	padding-block: 2px;
	padding-inline: 10px;
	border: 1px solid var(--ac-link);
	border-radius: var(--ac-radius-sm);
	background: transparent;
	color: var(--ac-link);
	font-size: 13px;
	font-weight: 600;
	cursor: pointer;
	transition: background-color 150ms ease-out;
}

.toast-action:hover {
	background: var(--ac-surface-2);
}

.toast-close {
	display: inline-flex;
	flex: none;
	align-items: center;
	justify-content: center;
	inline-size: 28px;
	block-size: 28px;
	padding: 0;
	border: 0;
	border-radius: var(--ac-radius-sm);
	background: transparent;
	color: var(--ac-muted);
	cursor: pointer;
}

.toast-close:hover {
	color: var(--ac-ink);
}

.toast-close svg {
	inline-size: 16px;
	block-size: 16px;
}

@keyframes ac-toast-in {
	from {
		opacity: 0;
		transform: translateY(8px);
	}
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
