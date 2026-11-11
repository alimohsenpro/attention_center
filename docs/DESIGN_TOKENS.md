# Attention Center — Design Tokens

The default look: a calm, official dashboard style — deep green with restrained gold accents,
pale green-grey surfaces, rounded cards, and a four-step priority colour scale. Tokens are CSS
custom properties defined on the shadow host; an installation can override them later.
Do not use any organisation's name, logo or emblem.

## Colour

| Token | Light | Dark | Use |
|---|---|---|---|
| `--ac-green-900` | `#03302b` | same | deepest brand shade; window header gradient end |
| `--ac-green-800` | `#044640` | same | window header, launcher background |
| `--ac-green-700` | `#067564` | same | primary buttons, active tab, links |
| `--ac-green-500` | `#0e9f86` | same | positive status, "normal" priority, progress |
| `--ac-gold` | `#c59a42` | same | accents, counters on dark surfaces, "urgent" priority |
| `--ac-gold-soft` | `#f1d99a` | same | text on green header, subtle highlights |
| `--ac-surface` | `#ffffff` | `#18201f` | window and card background |
| `--ac-surface-2` | `#f5f8f7` | `#1f2a28` | table header, hovered row, summary strip |
| `--ac-ink` | `#17302c` | `#e8f0ee` | primary text |
| `--ac-muted` | `#63756f` | `#9db0aa` | secondary text, metadata |
| `--ac-border` | `#e3ebe8` | `#2c3a37` | hairlines, card borders |
| `--ac-track` | `#edf2f0` | `#2a3633` | empty progress, skeletons |
| `--ac-shadow` | `0 10px 28px -16px rgba(0,0,0,.35)` | `0 10px 28px -16px rgba(0,0,0,.6)` | floating surfaces only |

Priority scale (text or border colour, with a tinted background at about 12 % opacity):

| Priority | Token | Value | Arabic label |
|---|---|---|---|
| immediate | `--ac-p-immediate` | `#c0392b` | فوري |
| urgent (very) — reserved for sources that distinguish it | `--ac-p-very` | `#e0703a` | عاجل جداً |
| urgent | `--ac-p-urgent` | `#c59a42` | عاجل |
| normal | `--ac-p-normal` | `#0e9f86` | عادي |

The source contract has three priorities (`normal`, `urgent`, `immediate`); `--ac-p-very` exists
for a future fourth level and for overdue accents. Overdue rows use `--ac-p-immediate` for the
edge stripe and the age text.

Status colours for `status_color`: `gray #9aa9b5`, `blue #3b82a0`, `green #0e9f86`,
`orange #c59a42`, `red #d0574b`.

Dark mode follows the desk (`data-theme="dark"` on `<html>`), not the OS setting. Text on
coloured backgrounds must reach a 4.5:1 contrast ratio; `node --test tests/js/contrast.test.js`
checks the pairs the stylesheets use, in both themes, and prints each ratio.

## Shape, spacing, type

- Radius: `--ac-radius-sm: 8px` (inputs, small buttons), `--ac-radius: 12px` (rows, cards), `--ac-radius-lg: 18px` (window, panel), pills `999px`.
- Spacing scale: 4, 8, 12, 16, 24 px. Row padding 12 × 16. Window padding 16–24.
- Font: inherit the desk's font family so Arabic renders in the site's typeface. Sizes: 12 (metadata), 13 (table), 14 (body), 16 (window title). Weights: 400 body, 600 labels, 700 titles and counters. Line-height 1.6 for Arabic.
- Numbers in counters and ages use tabular figures (`font-variant-numeric: tabular-nums`).
- Borders are 1 px `--ac-border`. Shadows only on the launcher, toasts and the floating window.

## Components

- **Launcher**: pill, `--ac-green-800` background, `--ac-gold-soft` icon and label, counter in a gold pill with `--ac-green-900` text; collapsed state is a 44 px circle with the counter as a badge. A thin gold ring pulses once on new items (no pulse under `prefers-reduced-motion`). When attention items exist the counter pill uses `--ac-p-immediate` with white text.
- **Window header**: horizontal gradient `--ac-green-800 → --ac-green-900`, title in white, a 2 px gold line under it (`linear-gradient(90deg, transparent, var(--ac-gold) 30%, var(--ac-gold-soft) 50%, var(--ac-gold) 70%, transparent)`). Header actions: settings, mode, close.
- **Tabs**: text tabs with a counter pill; the active tab has `--ac-green-700` text and a 2 px underline; counters of tabs with attention items use the immediate colour.
- **Table**: header row on `--ac-surface-2`, 13 px, muted text. Rows separated by hairlines; hover uses `--ac-surface-2`. Overdue rows have a 3 px stripe on the inline-start edge in `--ac-p-immediate` and show the age in that colour. Priority is a pill with icon + text (never colour alone). The "Open" control is a small outlined button in `--ac-green-700`.
- **Stacked rows** (panel, drawer, narrow dialog): card per item, 12 px radius, title on the first line, metadata line below, priority pill and age on the inline-end side.
- **Summary strip** ("new since you last looked"): `--ac-surface-2` background, gold icon.
- **Toasts**: cards on `--ac-surface` with a 3 px inline-start stripe coloured by priority, an icon, one line of text and one action; maximum three stacked above the launcher.
- **Empty state**: one line of muted text with a check icon in `--ac-green-500` ("Nothing is waiting on you" / «لا شيء ينتظرك الآن»). **Error state**: one line with a retry link.
- **Icons**: inline SVG, 1.75 px stroke, rounded caps, 20 px grid; a small bundled set (bell, check, clock, alert-triangle, inbox, user-check, megaphone, settings, volume, volume-off, x, chevrons, external-link).

## Motion

150–200 ms ease-out for open/close and toasts; no looping animation except the single pulse on
new items. Everything is disabled under `prefers-reduced-motion: reduce`.

## Tone names (for labels and translations)

| id | English | Arabic |
|---|---|---|
| chime | Chime | رنّة |
| knock | Knock | طرقة |
| pulse | Pulse | نبضة |
| telegraph | Telegraph | برقية |
| drop | Drop | قطرة |
| urgent | Urgent | عاجل |
| immediate | Immediate | فوري |
| reminder | Reminder | تذكير |
