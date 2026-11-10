// The window's stylesheet, added to the shadow root with the window bundle so that the launcher bundle stays
// small [NFR-PERF-02]. Tokens come from the host (ui/styles.js); logical properties only (§7.1).
export const WINDOW_STYLES = `
.overlay {
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

.window {
	--ac-link: var(--ac-green-700);
	display: flex;
	flex-direction: column;
	inline-size: min(1040px, 100%);
	max-block-size: min(720px, 100%);
	overflow: hidden;
	border-radius: var(--ac-radius-lg);
	background: var(--ac-surface);
	color: var(--ac-ink);
	box-shadow: var(--ac-shadow);
	font-size: 14px;
	line-height: 1.6;
	animation: ac-rise 200ms ease-out;
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

.tabs {
	display: flex;
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

@keyframes ac-rise {
	from {
		opacity: 0;
		transform: translateY(8px);
	}
}
`;
