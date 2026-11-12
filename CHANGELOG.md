# Changelog

All notable changes to Attention Center. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- **Announcements (backend).** `Attention Announcement` (title, sanitised rich-text body, priority,
  validity window, audience of all desk users, roles or user groups, optional acknowledgement) and
  `Attention Announcement Receipt` (one per user and announcement). A built-in action source lists
  the announcements a user receives; those awaiting the user's acknowledgement count as action items.
  Endpoints `acknowledge_announcement` and, for managers, `get_announcement_receipts` (who
  acknowledged and who has not). Desk users can open only the announcements they receive.
- **Announcements (window and receipts).** An Announcements tab after the info sources lists the
  announcements a user receives; "Open" shows one in the window with its body and an Acknowledge
  button. The All tab lists the announcements awaiting acknowledgement. Immediate announcements raise
  a toast that stays until closed, also when the desk is opened after they were published, until the
  Announcements tab was viewed or the announcement acknowledged; a new announcement shows the
  launcher's dot. An announcement the user acknowledged or wrote is not new to them. Managers see who
  acknowledged and who has not in the report "Announcement Acknowledgements", with Frappe's export,
  from a button on the announcement's form or from the workspace. Endpoints `get_announcement`,
  `get_announcements_to_acknowledge` and `get_unseen_announcements`.
- **Remind me later.** A clock button beside "Open" on every item sets one of Frappe's reminders for the
  user, in an hour, tomorrow at 9:00 or at a time they pick, about the item's document (which they must
  be able to read). Endpoint `remind_me_later`. Items now carry the document they are about
  (`reference_doctype`, `reference_name`) next to their route.
- **Today's Events and Due Reminders.** Two built-in info sources: the events the user's Frappe calendar
  shows for today, repeating ones included, and the user's reminders that fell due in the last 24 hours.

## 0.1.0 — 2026-11-11

First release: the MVP of `docs/PRD.md`, every requirement marked 0.1.

### Added

- **Sources.** A registry fed by the `attention_sources` hook of every installed app (source contract
  v1, synced into `Attention Source` at install and migrate) and by sources created in the desk.
  Declarative DocType-query sources with `{user}` and `{today}` placeholders, priority maps and route
  fields; python sources from hooks only. A rejected hook entry is skipped and logged without stopping
  the others.
- **Built-in sources:** Approvals (open Workflow Actions, with a read-permission check per document),
  Assignments (open ToDos) and Notifications (unread Notification Logs).
- **Permissions and privacy.** Everything is computed as the session user with Frappe's
  permission-aware queries; no endpoint takes a user id; targeting by roles and user groups only
  narrows; logs, caches shared between users and realtime payloads carry no item content.
- **Fault isolation.** A failing or slow source shows as an error in its own tab; every database
  statement of a source is stopped after 2 seconds; counts are capped at 99, read from at most 100
  rows, and cached per user.
- **Server API:** summary, paginated items sorted overdue, immediate, urgent, then newest, "seen"
  watermarks, preferences, and "Test for my user" for managers; boot information without any source
  run.
- **Realtime.** Content-free nudges to the users a change concerns, after the commit and at most one
  per user per transaction, a site-wide broadcast for large or unknown audiences, and `nudge()` for
  consumer apps' changes that raise no document event. The client also refreshes on visibility,
  reconnect and a heartbeat.
- **Desk client** in one Shadow DOM: a launcher with counter and pulse, a window titled "What needs
  your attention" with a tab per source and an "All" tab, in dialog, panel or drawer mode, stacked
  rows below 720 px, a browser-tab counter, keyboard access (`Alt+Shift+A`, `Esc`, focus trap) and
  screen-reader announcements. A failure disables it for the page load without touching the desk.
- **Alerts.** Toasts for new items, one toast and one sound per burst, nothing for the user's own
  changes, a sticky toast for immediate items, the window opening once per login when action items
  wait, and a periodic reminder while urgent, immediate or overdue items wait.
- **Sound.** Eight generated tones (five standard, plus urgent, immediate and reminder), three sound
  scopes, volume, Do Not Disturb, `mute_sounds` respected, one tab playing each alert, and a hint
  when the browser blocks sound.
- **Settings and governance.** `Attention Center Settings` with every user default, the timings and
  the organisation's tones; per-user preferences edited in the window; the `Attention Manager` role;
  the `Attention Center` workspace; an option to hide the stock bell.
- **Languages and look.** A complete Arabic translation, right-to-left layout, light and dark themes,
  and design tokens checked against WCAG 2.1 AA contrast.
- **Documentation.** The provider guide `docs/PROVIDER_CONTRACT.md`, a tested sample consumer app in
  `examples/`, and performance measurements in `docs/PERF.md`.
