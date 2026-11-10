# Attention Center — Product Requirements (PRD)

Status: approved by the product owner on 2026-11-09. This file is the source of truth for
*what* to build. `docs/TECH_DESIGN.md` says *how*; `docs/DELIVERY_PLAN.md` says *in what order*.
If the three disagree, this file wins and the disagreement is a bug to report (see
`CLAUDE.md` → Escalation).

## 1. Problem and goal

Frappe signals new notifications with a small indicator on a bell icon. Work that is waiting on
a person lives in several shapes that the bell does not show:

| Shape | Example | Where it lives |
|---|---|---|
| Personal | a task assigned to me | `ToDo`, app-specific task DocTypes |
| Role-based | a document waiting for my approval | `Workflow Action` |
| Unit-based (shared queue) | incoming correspondence for my department | app-specific DocTypes scoped by an organisational unit |
| Event feed | "X mentioned you" | `Notification Log` (the only shape the bell shows) |

Because the bell covers only the last shape, each app starts building its own inbox, and people
miss approvals, assignments and urgent incoming items.

**Goal.** One reusable Frappe app that answers, for every desk user and across every installed
app: *"What needs me now?"* — and makes sure that what deserves an interruption actually
interrupts. The app never owns the work items; the source app stays the system of record.

### Non-goals

- NG-1 Executing business actions (approve, refer, reply) from inside the Attention Center. It opens the document; the user acts there.
- NG-2 Modifying, replacing or depending on Frappe's bell or any theme's bell.
- NG-3 Official circular / correspondence management, and SLA rule engines. Those belong to source apps and surface through sources.
- NG-4 Email, SMS, WhatsApp, mobile push, OS-level (browser Notification API) notifications. The last one is a later feature that needs HTTPS.
- NG-5 Sources that live outside the current site (REST ingestion).
- NG-6 A full-page inbox that duplicates the source apps' own list pages.
- NG-7 Storing copies of work items, or a second "read" state for them.

## 2. Personas

| ID | Persona | Needs |
|---|---|---|
| P1 | Staff member | See tasks assigned to me; notice new ones without watching the screen |
| P2 | Approver / manager | See everything waiting for my approval across apps |
| P3 | Unit or operations-room clerk | See my unit's shared incoming queue; be interrupted for urgent and immediate items; be reminded while they stay unhandled |
| P4 | Attention Manager (admin) | Decide which sources exist, who sees them, the defaults, and (v0.2) publish system announcements |
| P5 | Consumer-app developer | Plug an app's "waiting on you" lists into the Attention Center in under half a working day, without making the app depend on it |

Users are Arabic-speaking and mostly non-technical. Arabic (RTL) is the primary UI language;
English (LTR) must work equally well.

## 3. Glossary

- **Source**: a named feed of items for the current user (a tab). Defined either declaratively (a DocType query) or by Python callables shipped by an app.
- **Item**: one row in a source: something waiting on the user (kind `action`) or something to know (kind `info`).
- **Kind**: `action` (counts in the badge, may make a sound, stays until the work is done in the source app) or `info` (a feed; unseen marker only).
- **Priority**: `normal`, `urgent`, `immediate`. **Overdue**: an item whose due date/time has passed.
- **Attention items**: action items that are `urgent`, `immediate` or overdue.
- **Nudge**: a content-free realtime signal telling a user's browser to refresh its summary.
- **Launcher**: the small floating control fixed to the bottom inline-end corner. **Window**: the UI the launcher opens.

## 4. Functional requirements

Each requirement has an ID, a release (`0.1` = MVP, `0.2` = v1) and acceptance criteria (AC).
"The user" means the logged-in desk user.

### 4.1 Sources (SRC)

**FR-SRC-01 Source registry (0.1).** Sources come from two places: the `attention_sources` hook of any installed app, and `Attention Source` documents created by an Attention Manager.
- AC1 A source has: unique `key`, `label`, `kind`, `type` (`doctype_query` or `python`), enabled flag, sort order, optional targeting.
- AC2 Hook-declared sources are synced into `Attention Source` on `bench migrate`; their definition fields are read-only in the form; an admin can only enable/disable, reorder, relabel and target them.
- AC3 A hook entry with an unsupported `contract_version`, a duplicate key or missing required fields is skipped, logged once, and does not stop other sources from loading.
- AC4 Removing an app removes (disables) its hook sources at the next migrate without errors.

**FR-SRC-02 Declarative source (0.1).** A `doctype_query` source is defined by: DocType, filters, field mapping (title, from, date, priority, due, status), optional priority value map, optional recipient fields, optional "view all" route.
- AC1 Filters support the placeholders `{user}` (session user id) and `{today}` (site date).
- AC2 An Attention Manager can create one from the desk form without writing code, and test it with a "Test for my user" button that shows the count and the first items.
- AC3 Invalid definitions (unknown DocType, unknown field, malformed filters) are rejected on save with a clear message.

**FR-SRC-03 Python source (0.1).** An app can declare callables for count, items and (optionally) recipients.
- AC1 The consumer app does not import `attention_center`; with Attention Center uninstalled the consumer app behaves exactly as before.
- AC2 Python sources can only come from hooks. Creating one from the desk form is rejected.
- AC3 The callable contract (names, arguments, return shapes) is versioned (`contract_version: 1`) and documented in `docs/PROVIDER_CONTRACT.md` with a runnable example.

**FR-SRC-04 Built-in sources (0.1).**
- AC1 *Approvals*: open `Workflow Action` rows the user may act on, one item per document, only for documents the user can read.
- AC2 *Assignments*: open `ToDo` rows allocated to the user; `High` priority maps to `urgent`; the ToDo date is the due date.
- AC3 *Notifications* (kind `info`): unread `Notification Log` rows of the user.

**FR-SRC-05 Fault isolation (0.1).**
- AC1 An exception or timeout in one source marks only that source as `error` in the summary; other sources are returned normally.
- AC2 The failure is logged with the source key and the user, never with item content.

**FR-SRC-06 Item model (0.1).** Every item exposes: `id`, `title`, a way to open it (route), and optionally type label, from, date, priority, due, status label/colour.
- AC1 Items missing `id`, `title` or a route are dropped and logged; they never break the response.
- AC2 Titles and labels are treated as plain text end to end (escaped on render).

### 4.2 Permissions and privacy (PERM)

**FR-PERM-01 (0.1)** Counts and items are always computed on the server for the session user. No endpoint accepts a user identifier from the client.
- AC1 A test proves a user cannot obtain another user's summary or items by any parameter.

**FR-PERM-02 (0.1)** Declarative sources use Frappe's permission-aware list queries.
- AC1 Tests prove that documents hidden by role permissions, user permissions or `permission_query_conditions` are neither counted nor listed.

**FR-PERM-03 (0.1)** The approvals source checks read permission on each referenced document.
- AC1 A user who holds the workflow role but cannot read the document sees neither the item nor a count for it.

**FR-PERM-04 (0.1)** Admin targeting only narrows visibility.
- AC1 A source is visible to a user only if it is enabled, the user matches its targeting (or it has none), and — for declarative sources — the user has read permission on the DocType.
- AC2 No setting can make a user see an item they cannot open.

**FR-PERM-05 (0.1)** Realtime nudges carry no document data (only source keys, an actor id and a timestamp) and are sent to user rooms, or as a site-wide content-free broadcast when the audience is too large to enumerate.

**FR-PERM-06 (0.1)** The app stores no item copies. It stores only: settings, source definitions, per-user preferences, per-user "last seen" watermarks, and (0.2) announcements with acknowledgement receipts.

**FR-PERM-07 (0.1)** No request leaves the site: no CDN assets, no external fonts, no telemetry.

### 4.3 Server API (API)

**FR-API-01 Summary (0.1).** One call returns, per visible source: count (capped at 99, with a "more" flag), counts of urgent / immediate / overdue items, timestamp of the latest item, number of items newer than the user's watermark, and state (`ok`/`error`); plus totals.
- AC1 Counts are cached per user and source with a short TTL and invalidated by nudges.

**FR-API-02 Items (0.1).** Paginated items for one source, sorted: overdue first, then priority (immediate, urgent, normal), then newest.
- AC1 Requesting a source that is not visible to the user is rejected with a permission error.
- AC2 Page size is bounded server-side.

**FR-API-03 Watermarks (0.1).** Viewing a source marks it seen (stores the time); "new since seen" resets.

**FR-API-04 Preferences (0.1).** Get and set the user's own preferences; the server validates every field and ignores or rejects unknown ones.

### 4.4 Realtime (RT)

**FR-RT-01 (0.1)** When a document of a watched DocType changes, affected users are nudged after the transaction commits.
- AC1 The hook handler adds no measurable cost for unwatched DocTypes (constant-time lookup).
- AC2 Several changes in one request produce at most one nudge per user.

**FR-RT-02 (0.1)** The client stays correct without realtime: it refreshes when the tab becomes visible, when the socket reconnects, and on a slow heartbeat while visible.

**FR-RT-03 (0.1)** A public server function lets a consumer app nudge users for one of its sources when no document event exists (for example from a scheduler job).

### 4.5 User interface (UI)

**FR-UI-01 Launcher (0.1).** Fixed to the bottom inline-end corner (bottom-left in RTL, bottom-right in LTR) on every desk page; collapsible to an icon; shows the action count (`99+` cap), an "unseen info" dot, and pulses when something new arrives.
- AC1 It never covers Frappe modals (it sits below them) and is not rendered on non-desk pages.

**FR-UI-02 Window (0.1).** Titled "What needs your attention" (Arabic: «ما يحتاج انتباهك»). Tabs with counters: one per action source, an "All" action tab, the info sources, and (0.2) Announcements. Each tab shows a table: item, type/source, from, date/age, priority/due, status, and an "Open" control. Pagination. Loading, empty and error states per tab. "View all" opens the source app's own page when the source provides a route.
- AC1 "Open" navigates to the item's route and closes the window.
- AC2 Overdue and immediate/urgent rows are visually distinct without relying on colour alone.

**FR-UI-03 Display modes (0.1).** Three containers for the same content: centred dialog (default), panel anchored above the launcher, side drawer on the inline-end edge. The admin sets the default; the user may change it.

**FR-UI-04 Responsive (0.1).** Below 720 px of available width the table becomes stacked rows; the window is usable at 360 px.

**FR-UI-05 Style isolation (0.1).** The UI renders inside a Shadow DOM so that desk themes cannot restyle it and it cannot restyle the desk. It works on stock Frappe desk and on themes that replace the desk shell and navbar.
- AC1 No selector or script depends on Frappe's navbar or bell DOM.

**FR-UI-06 Browser-tab counter (0.1).** The document title shows `(N)` while N > 0 action items exist.

**FR-UI-07 Toasts (0.1).** New-item and reminder toasts appear near the launcher, never steal focus, auto-dismiss, and open the window on the relevant tab when clicked.

**FR-UI-08 Accessibility (0.1).** Keyboard shortcut to open/close; `Esc` closes; focus is trapped in the dialog and restored on close; tabs and table are navigable by keyboard; roles and labels for screen readers; new alerts are announced through a polite live region; animations respect `prefers-reduced-motion`.

**FR-UI-09 Languages (0.1).** Every user-visible string is translatable; a complete Arabic translation ships in `translations/ar.csv`; layout is correct in RTL and LTR; light and dark desk themes are supported.

**FR-UI-10 Visual identity (0.1).** The default look follows `docs/DESIGN_TOKENS.md`.

### 4.6 Alert policy (ALERT)

**FR-ALERT-01 Classification (0.1).** Every action item has a priority (`normal` default) and may be overdue.

**FR-ALERT-02 Decision rules (0.1).**

| Event | Badge | Toast | Sound |
|---|---|---|---|
| New `info` item | unseen dot | no | only if user scope = "everything" (standard tone) |
| New `action` item, normal | count | yes | if user scope ≥ "action items" (user's standard tone) |
| New `action` item, urgent | count + accent | yes | organisation "urgent" tone, at every scope |
| New `action` item, immediate | count + accent | yes, sticky until dismissed | organisation "immediate" tone, at every scope |
| Periodic reminder | — | yes | organisation "reminder" tone |

- AC1 Visual signals for urgent, immediate and overdue items cannot be disabled by the user.

**FR-ALERT-03 Coalescing (0.1).** Events arriving within the coalescing window (default 10 s) produce one toast ("N new items") and one sound: that of the highest priority in the burst.

**FR-ALERT-04 Self-suppression (0.1).** A change caused by the user's own action produces no sound and no toast for that user.

**FR-ALERT-05 Login (0.1).** After login, if the user has action items, the window opens automatically once per login session, with a "new since you last looked" summary line. With no action items nothing opens. The user may turn auto-open off.

**FR-ALERT-06 Periodic reminder (0.1).** While attention items exist, a reminder toast and tone repeat every N hours (admin default 2). It never opens the window by itself and never steals focus. One reminder per interval per browser, not per tab.

### 4.7 Sound (SND)

**FR-SND-01 Tone set (0.1).** The app bundles its own short, non-melodic tones: five selectable standard tones, plus fixed "urgent", "immediate" and "reminder" tones. Each is under two seconds, loudness-matched, generated by a script in the repository (no third-party audio).

**FR-SND-02 User control (0.1).** The user chooses: sound scope (`urgent only` / `action items` (default) / `everything`), standard tone (with preview), volume, and Do Not Disturb (1 hour / until end of day / off).
- AC1 Do Not Disturb and `User.mute_sounds` silence all sounds; visuals continue.

**FR-SND-03 Browser constraints (0.1).** If the browser blocks playback before the first user gesture, the launcher pulses, a one-time hint explains it, and sound starts working after the first interaction without a reload.

**FR-SND-04 One sound per alert (0.1).** With several tabs open, an alert plays in exactly one tab. This must work on plain-HTTP origins (no APIs that require a secure context).

### 4.8 Settings and governance (SET)

**FR-SET-01 Admin settings (0.1).** A single settings document: enable/disable the app; defaults for every user preference; reminder interval; coalescing window; heartbeat; page size; the three organisation tones; optional "hide Frappe's standard bell" (CSS only, default off).

**FR-SET-02 User preferences (0.1).** Stored per user, edited from the window's settings view; unset values fall back to admin defaults.

**FR-SET-03 Role (0.1).** A role `Attention Manager` (plus `System Manager`) manages settings and sources.

### 4.9 Announcements (ANN) — release 0.2

**FR-ANN-01** An Attention Manager publishes an announcement: title, body (sanitised rich text), priority, validity window, audience (all desk users, roles, user groups), and whether acknowledgement is required.
**FR-ANN-02** Announcements appear in an "Announcements" tab; unacknowledged ones requiring acknowledgement count as action items; `immediate` ones raise a sticky toast.
**FR-ANN-03** The user acknowledges with one click; the receipt (user, time) is stored once.
**FR-ANN-04** The manager sees who acknowledged and who has not, and can export the list.
- AC A user outside the audience can neither see nor acknowledge the announcement; receipts are visible to managers only.

### 4.10 Other 0.2 features

**FR-SNZ-01 Remind me later.** From any item the user can set a reminder (1 hour, tomorrow morning, custom) implemented with Frappe's `Reminder` DocType.
**FR-EXT-01 Extra built-in sources.** Today's calendar events and due reminders as `info` sources.
**FR-EXT-02 Source health.** A manager view listing each source's last error and typical response time.

## 5. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-PERF-01 | Summary responds in ≤ 200 ms (p95) with warm cache and ≤ 800 ms cold, with the three built-in sources and 10 000 rows per source DocType |
| NFR-PERF-02 | No blocking request during desk boot; the launcher bundle is ≤ 25 KB gzipped; the window code is loaded on first open |
| NFR-PERF-03 | Each source query is capped (100 rows for counting) and has a time budget; a slow source is reported as `error`, not awaited indefinitely |
| NFR-SEC-01 | Every whitelisted method validates types and bounds, uses parameterised queries only, and enforces role checks for admin operations |
| NFR-SEC-02 | No `eval`, no dynamic import of admin-supplied paths; Python sources are loaded only from hooks |
| NFR-SEC-03 | All rendered text is escaped; announcement bodies are sanitised on save |
| NFR-PRIV-01 | Logs and error reports contain source keys, user ids, counts and timings — never titles or document content |
| NFR-I18N-01 | 100 % of user-visible strings are wrapped for translation and present in `ar.csv` (checked by a test) |
| NFR-A11Y-01 | Keyboard-only operation and text contrast meeting WCAG 2.1 AA for the default tokens in light and dark |
| NFR-COMP-01 | Frappe 15.x; Python 3.10–3.12; Node 18+; MariaDB 10.6+. Depends only on `frappe` |
| NFR-COMP-02 | Latest two versions of Chrome, Edge and Firefox; plain-HTTP intranet origins supported |
| NFR-COMP-03 | No dependency on navbar/bell DOM, so that Frappe 16's sidebar layout does not break the app (not certified for v16 in 0.x) |
| NFR-REL-01 | The UI must never break the desk: every entry point is wrapped so that a failure disables the Attention Center for that page load and logs to the console |
| NFR-MAINT-01 | Backend logic and permission filtering are covered by tests that fail when the behaviour breaks; pure client logic has unit tests; CI is green before merge |

## 6. Release scope

| Release | Contents |
|---|---|
| 0.1 (MVP) | All requirements marked 0.1 |
| 0.2 (v1) | FR-ANN-01..04, FR-SNZ-01, FR-EXT-01, FR-EXT-02 |
| Later (not planned) | OS notifications (HTTPS), quick actions, cross-site sources, mobile push, email digests, analytics, escalation to managers, Frappe 16 certification |

## 7. Success measures

1. Median age of open `Workflow Action` rows drops one month after rollout.
2. At least 70 % of users still have sound enabled after one month.
3. A developer integrates a new source in half a working day or less using only `docs/PROVIDER_CONTRACT.md`.
4. Zero permission leaks in tests; zero desk breakages attributable to the app.
5. NFR-PERF-01 holds on the reference dataset.

## 8. Product decisions already taken

Recorded in `docs/DECISIONS.md`. Do not reopen them in code; escalate if one blocks you.
