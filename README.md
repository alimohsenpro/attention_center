# Attention Center

A Frappe app that shows every desk user **what needs them now** across all installed apps —
approvals, assignments, shared unit queues, notifications — and interrupts them with a badge, a
toast or a sound only when it is deserved.

- One floating launcher and one window on every desk page, isolated from desk themes.
- Sources are pluggable: define one from the desk (a DocType, filters and a few field mappings) or ship Python callables from your app through a hook. Your app keeps working without Attention Center.
- Everything is computed live, as the logged-in user, from the source app. No copies, no second "read" state.
- Arabic (RTL) and English, light and dark.

**Version 0.1.0.** What changed is in [`CHANGELOG.md`](CHANGELOG.md). Release 0.2 is planned to add
announcements with acknowledgement, "remind me later", calendar and reminder sources, and a source
health view (`docs/PRD.md`, section 6).

## Requirements

- Frappe 15.x, Python 3.10–3.12, Node 18 or later, MariaDB 10.6 or later. No other dependency.
- The latest two versions of Chrome, Edge or Firefox. Plain-HTTP intranet sites work.
- Realtime updates use Frappe's socket server when it runs; without it the window still refreshes on its own (see Limits).

## Install

```bash
cd ~/frappe-bench
bench get-app <repository url> --branch main
bench --site <site> install-app attention_center
bench build --app attention_center      # when get-app was run with --skip-assets
bench restart                           # production benches
```

The install creates the role **Attention Manager**, the settings, and the built-in sources:
**Approvals** (open Workflow Actions on documents the user may read), **Assignments** (open ToDos
allocated to the user), **Notifications** (the user's unread Notification Logs) and, on the way to
release 0.2, **Announcements** (the announcements the user receives). Every desk user
then gets the launcher in the bottom corner on the inline-end side (bottom left in Arabic, bottom
right in English); `Alt+Shift+A` opens and closes the window.

**Upgrade:** `bench update --apps attention_center`, or `git pull` in `apps/attention_center` followed by
`bench --site <site> migrate` and `bench build --app attention_center`.

**Apps that declare sources:** their sources are read at every `bench --site <site> migrate` and when
Attention Center is installed. After installing such an app, or uninstalling one, run `migrate`.

**Uninstall:** `bench --site <site> uninstall-app attention_center`. Apps that declare sources keep
working: they never import Attention Center.

## Configuration

System Managers and Attention Managers find everything in the **Attention Center** workspace.

### Attention Center Settings

| Setting | Default | Notes |
|---|---|---|
| Enabled | on | Off: no launcher, and the API shows no source to anyone |
| Hide Standard Bell | off | Hides the bell of the stock Frappe 15 navbar with CSS. Themes and Frappe 16 keep theirs |
| Default Display Mode | Dialog | Dialog, Panel (above the launcher) or Drawer (along the inline-end edge) |
| Default Auto Open on Login | on | The window opens once per login when the user has action items |
| Default Sound Scope | Action Items | Urgent Only, Action Items or Everything |
| Default Tone, Default Volume | Chime, 60 | Five standard tones; volume 0–100 |
| Urgent, Immediate, Reminder Tone | Urgent, Immediate, Reminder | The organisation's tones; users cannot change them |
| Reminder Interval Hours | 2 | While urgent, immediate or overdue items wait; 0 turns reminders off, otherwise at least 0.25 |
| Coalesce Seconds | 10 | Items arriving within this window make one toast and one sound (1–120) |
| Heartbeat Seconds | 300 | How often a visible tab refreshes without a realtime signal (60–3600) |
| Summary Cache TTL | 60 | Seconds a user's counts are kept (5–600) |
| Page Size | 10 | Items per page in the window (5–50) |

Users get changed settings at their next page load. The "Default" settings apply to every user who
has not chosen otherwise in the window's own settings view (sound scope, tone with preview, volume,
Do Not Disturb, auto-open, display mode).

### Attention Source

One document per source (`/app/attention-source`).

- **Sources declared by apps** (system sources) can be enabled or disabled, reordered (Sort Order), relabelled and targeted. Their definition is the app's and is read-only.
- **Targeting:** with no roles and no user groups, every desk user sees the source; otherwise a user needs one of the roles or membership in one of the groups. Targeting only narrows: nobody sees an item they could not open.
- **New sources from the desk** are DocType queries: a DocType, filters as JSON (`[["status", "=", "Open"], ["assigned_to", "=", "{user}"]]`, with the placeholders `{user}` and `{today}`), the fields for title, date, from, priority, due and status, an optional priority map, recipient fields and a "View all" route. A user sees such a source only if they may read its DocType.
- **Test for my user** runs a saved source with your own permissions and shows the count, the first five items and the duration.

### Attention Announcement

Release 0.2 work in progress: the backend is in place, the window's Announcements tab and acknowledge
button come next. One document per announcement (`/app/attention-announcement`).

- **Audience:** All Desk Users, or the holders of any listed role and the members of any listed user group. A user outside the audience can neither see nor acknowledge it.
- **Published** and the **Valid From** / **Valid To** window decide when it shows; publishing moves an empty or earlier start to the moment of publishing. Unpublish an announcement rather than delete it once users acknowledged it.
- **Requires Acknowledgement:** until a user acknowledges it, it counts among their action items, with its priority. Who acknowledged and when is in **Attention Announcement Receipt**, which only System Managers and Attention Managers can read and export.
- The body is rich text, sanitised on every save.

### Sources from your own app

Declare them in your app's `hooks.py`: [`docs/PROVIDER_CONTRACT.md`](docs/PROVIDER_CONTRACT.md) is the
complete guide, and [`examples/`](examples/) holds a tested sample app with one declarative and one
python source.

## Limits

- **Capped counts.** A count reads the newest 100 rows of a source and shows "99+" beyond 99. An urgent or overdue row older than the newest 100 is not counted, and past 100 pending rows the rest of a list is in date order only.
- **Freshness.** Counts are kept per user for the Summary Cache TTL. A change saved as a document refreshes the users concerned at once (with the socket server); a change made with a direct database write (for example Frappe's bell marking notifications read, or a bulk update by an app that does not call `nudge`) shows within the TTL after the next refresh. Without the socket server, a tab refreshes when it becomes visible and on the heartbeat.
- **Time budget.** Each database statement of a source is stopped after 2 seconds; a source that fails or times out shows as an error in its tab for that user, and the other sources load.
- **Announcements** count and list the newest 100 a user receives. A start or end time passing raises no event, so the announcement appears or leaves at the user's next refresh after the Summary Cache TTL.
- **Approvals** examine the newest 100 open Workflow Actions, with one read-permission check per document. Approvers are nudged without evaluating transition conditions, so a few more users than necessary may refresh.
- **Sound** plays in one tab per browser, not once per user across devices. Browsers block sound until the user first interacts with the page; the launcher pulses and a hint explains it.
- **Not included:** acting on items from the window (it opens the document), browser or OS notifications (they need HTTPS), email, SMS and mobile push, sources from other sites, and a full-page inbox.
- **Languages:** English and Arabic ship; other languages need translations.
- **Compatibility:** tested on the stock Frappe 15 desk. Desk themes are supported by design (Shadow DOM, no dependency on the navbar) but should be checked on your bench; Frappe 16 is not certified.

## Development

See `CLAUDE.md` for commands and conventions. `bash scripts/dev/bench_up.sh` builds a test
bench; `bash scripts/ci/run_tests.sh` runs everything CI runs. Requirements are in `docs/PRD.md`,
the design in `docs/TECH_DESIGN.md`, the plan in `docs/DELIVERY_PLAN.md`.

## Licence

MIT. Third-party skill files under `.claude/skills/` keep their own licences, listed in
`.claude/skills/NOTICE.md`.
