// The window's stylesheet, added to the shadow root with the window bundle so that the launcher bundle stays
// small [NFR-PERF-02]. Tokens come from the host (ui/styles.js); logical properties only (§7.1).
//
// The frame's data-mode selects the container [FR-UI-03]: the dialog is centred over a backdrop; the panel
// floats above the launcher and the drawer along the inline-end edge, with no backdrop, so the frame of those
// two takes no space and no clicks. All three sit below the desk's modals (z-index 1040/1050).
export const WINDOW_STYLES = `
.frame[data-mode="dialog"] {
	position: fixed;
	inset: 0;
	z-index: 1030;
	display: flex;
	align-items: center;
	justify-content: center;
	padding: 16px;
	background: rgba(3, 48, 43, 0.45);
	animation: ac-fade 150ms ease-out;
}

.frame:not([data-mode="dialog"]) {
	display: contents;
}

.window {
	--ac-link: var(--ac-green-700);
	container: ac-window / inline-size;
	display: flex;
	flex-direction: column;
	overflow: hidden;
	border-radius: var(--ac-radius-lg);
	background: var(--ac-surface);
	color: var(--ac-ink);
	box-shadow: var(--ac-shadow);
	font-size: 14px;
	line-height: 1.6;
	animation: ac-rise 200ms ease-out;
}

[data-mode="dialog"] > .window {
	inline-size: min(1040px, 100%);
	max-block-size: min(720px, 100%);
}

[data-mode="panel"] > .window,
[data-mode="drawer"] > .window {
	position: fixed;
	z-index: 1030;
	border: 1px solid var(--ac-border);
}

/* Above the launcher: its 16 px offset, its 44 px height and a 12 px gap. */
[data-mode="panel"] > .window {
	inset-block-end: 72px;
	inset-inline-end: 16px;
	inline-size: min(380px, calc(100% - 32px));
	max-block-size: min(640px, calc(100% - 88px));
}

[data-mode="drawer"] > .window {
	--ac-slide-from: 16px;
	inset-block: 0;
	inset-inline-end: 0;
	inline-size: min(420px, 100%);
	border-block: 0;
	border-inline-end: 0;
	border-start-end-radius: 0;
	border-end-end-radius: 0;
	animation-name: ac-slide;
}

/* Transforms have no logical direction: in right-to-left text the drawer comes from the left. */
:host([dir="rtl"]) [data-mode="drawer"] > .window {
	--ac-slide-from: -16px;
}

/* The drawer covers the launcher's corner. The launcher steps aside meanwhile, so that Tab never moves focus
   onto a control nobody can see. */
.launcher:has(~ .frame[data-mode="drawer"]:not([hidden])) {
	visibility: hidden;
}

/* Green 700 is too dark on the dark surface for text (WCAG AA); green 500 is the same hue, lighter. */
:host([data-theme="dark"]) .window {
	--ac-link: var(--ac-green-500);
}

.window:focus {
	outline: none;
}

.window-header {
	position: relative;
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	padding-block: 12px;
	padding-inline: 24px 12px;
	background: linear-gradient(90deg, var(--ac-green-800), var(--ac-green-900));
	color: #ffffff;
}

.window-actions {
	display: flex;
	flex: none;
	gap: 4px;
}

/* Gradients have no logical direction: the deeper shade stays at the inline end. */
:host([dir="rtl"]) .window-header {
	background: linear-gradient(270deg, var(--ac-green-800), var(--ac-green-900));
}

.window-header::after {
	content: "";
	position: absolute;
	inset-inline: 0;
	inset-block-end: 0;
	block-size: 2px;
	background: linear-gradient(
		90deg,
		transparent,
		var(--ac-gold) 30%,
		var(--ac-gold-soft) 50%,
		var(--ac-gold) 70%,
		transparent
	);
}

.window-title {
	margin: 0;
	font-size: 16px;
	font-weight: 700;
}

/* The "new since you last looked" line of the window that opened by itself at login. */
.summary-strip {
	display: flex;
	flex: none;
	align-items: center;
	gap: 8px;
	margin: 0;
	padding-block: 8px;
	padding-inline: 24px;
	background: var(--ac-surface-2);
	font-size: 13px;
	font-weight: 600;
}

.summary-strip svg {
	flex: none;
	color: var(--ac-gold);
}

.icon-button {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	inline-size: 36px;
	block-size: 36px;
	padding: 0;
	border: 0;
	border-radius: var(--ac-radius-sm);
	background: transparent;
	color: var(--ac-gold-soft);
	cursor: pointer;
	transition: background-color 150ms ease-out;
}

.icon-button:hover {
	background: rgba(255, 255, 255, 0.12);
}

:host([dir="rtl"]) .mode-button svg {
	transform: scaleX(-1);
}

.icon-button[aria-pressed="true"] {
	background: rgba(255, 255, 255, 0.18);
	color: #ffffff;
}

/* The tabs and their panel keep the window's column layout; the settings view takes their place. */
.items-view {
	display: contents;
}

/* The settings view [FR-SET-02]. */
.settings {
	flex: 1;
	min-block-size: 0;
	overflow: auto;
	padding-block: 16px 24px;
	padding-inline: 24px;
}

/* Native controls follow the desk's theme, not the OS setting. */
:host([data-theme="dark"]) .settings {
	color-scheme: dark;
}

.settings-top {
	display: flex;
	flex-wrap: wrap;
	align-items: baseline;
	justify-content: space-between;
	gap: 4px 12px;
}

.settings-title {
	margin: 0;
	font-size: 16px;
	font-weight: 700;
}

.settings-title:focus {
	outline: none;
}

.settings-status {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	min-block-size: 20px;
	margin: 0;
	color: var(--ac-muted);
	font-size: 12px;
}

.settings-group {
	margin-block-start: 12px;
	padding-block-start: 12px;
	border-block-start: 1px solid var(--ac-border);
}

.settings-heading {
	margin: 0;
	font-size: 14px;
	font-weight: 700;
}

.settings-field {
	min-inline-size: 0;
	margin: 0;
	margin-block-start: 12px;
	padding: 0;
	border: 0;
}

.settings-label {
	display: block;
	margin-block-end: 4px;
	padding: 0;
	font-size: 13px;
	font-weight: 600;
}

.choice {
	display: flex;
	align-items: center;
	gap: 8px;
	padding-block: 4px;
	cursor: pointer;
}

.choice input {
	flex: none;
	inline-size: 16px;
	block-size: 16px;
	margin: 0;
	accent-color: var(--ac-link);
	cursor: pointer;
}

.settings-row {
	display: flex;
	flex-wrap: wrap;
	align-items: center;
	gap: 8px 12px;
}

.settings-select {
	min-inline-size: 160px;
	padding-block: 4px;
	padding-inline: 8px;
	border: 1px solid var(--ac-border);
	border-radius: var(--ac-radius-sm);
	background: var(--ac-surface);
	color: var(--ac-ink);
	font: inherit;
	font-size: 13px;
}

.preview-button {
	display: inline-flex;
	align-items: center;
	gap: 6px;
}

.preview-button svg {
	inline-size: 16px;
	block-size: 16px;
}

/* The speaker faces the inline start in left-to-right text, its waves the inline end. */
:host([dir="rtl"]) .preview-button svg {
	transform: scaleX(-1);
}

.settings-range {
	flex: 1;
	max-inline-size: 260px;
	margin: 0;
	accent-color: var(--ac-link);
}

.settings-output {
	min-inline-size: 40px;
	font-size: 13px;
	font-variant-numeric: tabular-nums;
}

.hint {
	margin-block: 4px 0;
	color: var(--ac-muted);
	font-size: 12px;
}

.settings-note {
	margin-block: 12px 0;
	padding-block: 8px;
	padding-inline: 12px;
	border-radius: var(--ac-radius-sm);
	background: var(--ac-surface-2);
	font-size: 13px;
}

/* The tab strip keeps its height when the window is short; the items scroll instead. */
.tabs {
	display: flex;
	flex: none;
	gap: 4px;
	padding-inline: 16px;
	border-block-end: 1px solid var(--ac-border);
	overflow-x: auto;
}

.tab {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	padding-block: 12px 10px;
	padding-inline: 12px;
	border: 0;
	border-block-end: 2px solid transparent;
	background: transparent;
	color: var(--ac-muted);
	font-size: 14px;
	font-weight: 600;
	white-space: nowrap;
	cursor: pointer;
	transition: color 150ms ease-out;
}

.tab:hover {
	color: var(--ac-ink);
}

.tab[aria-selected="true"] {
	border-block-end-color: var(--ac-link);
	color: var(--ac-link);
}

.tab-count {
	min-inline-size: 22px;
	padding-inline: 6px;
	border-radius: 999px;
	background: var(--ac-surface-2);
	color: var(--ac-ink);
	font-size: 12px;
	font-weight: 700;
	line-height: 22px;
	text-align: center;
	font-variant-numeric: tabular-nums;
}

.tab[data-attention] .tab-count {
	background: var(--ac-p-immediate);
	color: #ffffff;
}

.tab-dot {
	inline-size: 8px;
	block-size: 8px;
	border-radius: 999px;
	background: var(--ac-gold);
}

.panel {
	display: flex;
	flex: 1;
	flex-direction: column;
	min-block-size: 0;
}

.panel-toolbar {
	display: flex;
	justify-content: flex-end;
	padding-block: 8px 0;
	padding-inline: 16px;
}

.view-all {
	display: inline-flex;
	align-items: center;
	gap: 4px;
	color: var(--ac-link);
	font-size: 13px;
	font-weight: 600;
	text-decoration: none;
}

.view-all:hover {
	text-decoration: underline;
}

.view-all svg {
	inline-size: 16px;
	block-size: 16px;
}

:host([dir="rtl"]) .view-all svg {
	transform: scaleX(-1);
}

.panel-content {
	flex: 1;
	min-block-size: 0;
	overflow: auto;
}

.state,
.empty,
.notice {
	display: flex;
	flex-wrap: wrap;
	align-items: center;
	gap: 8px;
	color: var(--ac-muted);
}

.state,
.empty {
	padding: 24px;
}

.empty svg {
	color: var(--ac-green-500);
}

.state svg,
.notice svg {
	color: var(--ac-p-immediate);
}

.notice {
	margin-block: 12px 0;
	margin-inline: 16px;
	padding-block: 8px;
	padding-inline: 12px;
	border-radius: var(--ac-radius-sm);
	background: var(--ac-surface-2);
	font-size: 13px;
}

.link-button {
	padding: 0;
	border: 0;
	background: none;
	color: var(--ac-link);
	font-weight: 600;
	text-decoration: underline;
	cursor: pointer;
}

.table-wrap {
	overflow-x: auto;
}

table {
	inline-size: 100%;
	border-collapse: collapse;
	font-size: 13px;
}

th {
	padding-block: 8px;
	padding-inline: 16px;
	background: var(--ac-surface-2);
	color: var(--ac-muted);
	font-weight: 600;
	text-align: start;
	white-space: nowrap;
}

td {
	padding-block: 12px;
	padding-inline: 16px;
	border-block-start: 1px solid var(--ac-border);
	vertical-align: top;
}

tbody tr:hover {
	background: var(--ac-surface-2);
}

.cell-item {
	position: relative;
	min-inline-size: 200px;
}

tr[data-overdue] .cell-item::before {
	content: "";
	position: absolute;
	inset-block: 0;
	inset-inline-start: 0;
	inline-size: 3px;
	background: var(--ac-p-immediate);
}

.item-title {
	font-weight: 600;
	overflow-wrap: anywhere;
}

td > span {
	display: block;
}

td > .pill {
	display: inline-flex;
}

td > .pill + .pill {
	margin-block-start: 4px;
}

.muted {
	color: var(--ac-muted);
	font-size: 12px;
}

time {
	white-space: nowrap;
}

tr[data-overdue] time {
	color: var(--ac-p-immediate);
}

/* The immediate red reaches 3:1 on the dark surface; the overdue accent of the scale reaches 4.6:1. */
:host([data-theme="dark"]) tr[data-overdue] time {
	color: var(--ac-p-very);
}

.pill {
	align-items: center;
	gap: 4px;
	padding-block: 0;
	padding-inline: 6px 8px;
	border-radius: 999px;
	font-size: 12px;
	font-weight: 700;
	line-height: 22px;
	white-space: nowrap;
}

.pill svg {
	inline-size: 14px;
	block-size: 14px;
}

.pill[data-kind="immediate"],
.pill[data-kind="overdue"] {
	background: var(--ac-p-immediate);
	color: #ffffff;
}

.pill[data-kind="urgent"] {
	background: var(--ac-p-urgent);
	color: var(--ac-green-900);
}

.status {
	display: inline-flex;
	align-items: center;
	gap: 6px;
}

.status::before {
	content: "";
	flex: none;
	inline-size: 8px;
	block-size: 8px;
	border-radius: 999px;
	background: #9aa9b5;
}

.status[data-color="blue"]::before {
	background: #3b82a0;
}

.status[data-color="green"]::before {
	background: #0e9f86;
}

.status[data-color="orange"]::before {
	background: #c59a42;
}

.status[data-color="red"]::before {
	background: #d0574b;
}

.open-link {
	display: inline-flex;
	padding-block: 2px;
	padding-inline: 12px;
	border: 1px solid var(--ac-link);
	border-radius: var(--ac-radius-sm);
	color: var(--ac-link);
	font-weight: 600;
	text-decoration: none;
	white-space: nowrap;
	transition: background-color 150ms ease-out, color 150ms ease-out;
}

.open-link:hover {
	background: var(--ac-link);
	color: #ffffff;
}

.pager {
	display: flex;
	align-items: center;
	justify-content: flex-end;
	gap: 8px;
	padding-block: 12px;
	padding-inline: 16px;
	border-block-start: 1px solid var(--ac-border);
}

.page-label {
	color: var(--ac-muted);
	font-size: 13px;
	font-variant-numeric: tabular-nums;
}

.pager-button {
	padding-block: 4px;
	padding-inline: 12px;
	border: 1px solid var(--ac-border);
	border-radius: var(--ac-radius-sm);
	background: var(--ac-surface);
	color: var(--ac-ink);
	font-size: 13px;
	font-weight: 600;
	cursor: pointer;
}

.pager-button:hover:not([disabled]) {
	background: var(--ac-surface-2);
}

.pager-button[disabled] {
	opacity: 0.5;
	cursor: default;
}

@keyframes ac-fade {
	from {
		opacity: 0;
	}
}

/* Each item as a card [FR-UI-04]: the title with the priority at its inline end, then a line of type, source,
   sender and status with the age and "Open" at its inline end; "Open" keeps to the inline end when it wraps.
   The panel (380 px) and the drawer (420 px) are always this narrow; the dialog is when the screen is. The
   table's header stays for screen readers. */
@container ac-window (width < 720px) {
	.window-header {
		padding-inline: 16px 8px;
	}

	.summary-strip,
	.settings {
		padding-inline: 16px;
	}

	.tabs {
		flex-wrap: wrap;
		gap: 0 4px;
		padding-inline: 8px;
	}

	.tab {
		padding-inline: 8px;
	}

	.table-wrap {
		overflow-x: visible;
	}

	table,
	td {
		display: block;
	}

	thead {
		position: absolute;
		inline-size: 1px;
		block-size: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
	}

	tbody {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px;
	}

	tbody tr {
		position: relative;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 12px;
		padding-block: 12px;
		padding-inline: 16px;
		overflow: hidden;
		border: 1px solid var(--ac-border);
		border-radius: var(--ac-radius);
	}

	/* Ends the title line, so that the metadata starts a line of its own. */
	tbody tr::before {
		content: "";
		order: 3;
		flex-basis: 100%;
	}

	/* Takes the free space between the metadata and the age, so that it does not reach the auto margin of
	   "Open", which then only acts when "Open" wraps onto a line of its own. */
	tbody tr::after {
		content: "";
		order: 5;
		flex: 1 0 0;
	}

	td {
		padding: 0;
		border: 0;
	}

	td:empty {
		display: none;
	}

	/* The overdue stripe runs along the card's edge rather than the title's. */
	.cell-item {
		position: static;
		order: 1;
		flex: 1 1 0;
		align-self: flex-start;
		min-inline-size: 0;
	}

	.cell-priority {
		order: 2;
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		align-self: flex-start;
		gap: 4px;
	}

	td.cell-priority > .pill + .pill {
		margin-block-start: 0;
	}

	.cell-type,
	.cell-from,
	.cell-status {
		order: 4;
		color: var(--ac-muted);
		font-size: 12px;
	}

	.cell-type {
		display: flex;
		flex-wrap: wrap;
		gap: 0 8px;
	}

	.cell-date {
		order: 6;
		color: var(--ac-muted);
		font-size: 12px;
	}

	.cell-open {
		order: 7;
		margin-inline-start: auto;
	}
}

@keyframes ac-rise {
	from {
		opacity: 0;
		transform: translateY(8px);
	}
}

@keyframes ac-slide {
	from {
		opacity: 0;
		transform: translateX(var(--ac-slide-from));
	}
}
`;
