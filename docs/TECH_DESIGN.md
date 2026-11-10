# Attention Center — Technical Design

Implements `docs/PRD.md` (requirement IDs in brackets). Target: Frappe 15.x, Python ≥ 3.10,
Node ≥ 18. The app depends only on `frappe`.

Facts about Frappe internals stated here were read from Frappe 15.91. When one matters to your
task, confirm it in the Frappe source of your bench (`apps/frappe`) before relying on it, and
fix this document in the same PR if it is wrong.

## 1. Principles

1. **State, not events.** We show work that is still waiting, computed live from the source app.
2. **The source is the system of record.** No item copies, no second read-state [FR-PERM-06].
3. **Everything runs as the session user.** Permission filtering is done by Frappe and by the source, never re-implemented by guessing [FR-PERM-01..04].
4. **Own the surface.** One Shadow DOM host appended to `document.body`; nothing depends on the navbar or bell [FR-UI-05, NFR-COMP-03].
5. **Realtime is an optimisation.** The client is correct with polling alone [FR-RT-02].
6. **Fail closed, fail small.** A broken source shows an error tab; a broken client disables itself for the page load [FR-SRC-05, NFR-REL-01].
7. KISS / YAGNI: no framework on the client, no new infrastructure on the server.

## 2. Repository layout (target)

```
attention_center/                     Python package
  hooks.py
  api.py                              whitelisted endpoints
  boot.py                             extend_bootinfo
  install.py                          after_install / after_migrate
  engine/
    contract.py                       constants, TypedDicts, validation of source defs and items
    registry.py                       load sources (hooks + DB), visibility for a user
    doctype_query.py                  declarative source executor
    runner.py                         run a source safely: timing, caps, isolation, cache
    recipients.py                     who to nudge for a changed document
    realtime.py                       doc-event handler, after-commit nudges, nudge() API
    preferences.py                    defaults + per-user preferences, watermarks
  sources/
    approvals.py                      Workflow Action (python source)
    builtin.py                        definitions of the built-in sources
  attention_center/doctype/           DocTypes (module "Attention Center")
  public/js/attention_center/         client source (ES modules)
  public/js/attention_center.bundle.js          launcher entry (always loaded)
  public/js/attention_center_window.bundle.js   window entry (lazy)
  public/sounds/                      generated tones (.wav) + tones.json
  translations/ar.csv
  tests/                              cross-cutting backend tests (DocType tests live with DocTypes)
scripts/                              ci/, dev/, pipeline/, sounds/
docs/  pipeline/  .claude/skills/
```

## 3. Data model

All DocTypes are in module `Attention Center`. Field names below are fieldnames; labels are the
title-cased English form and are translated.

### 3.1 `Attention Center Settings` (Single) [FR-SET-01]

| Field | Type | Default | Notes |
|---|---|---|---|
| `enabled` | Check | 1 | Off = no client assets act, endpoints return an empty summary |
| `default_display_mode` | Select `Dialog\nPanel\nDrawer` | Dialog | |
| `default_auto_open_on_login` | Check | 1 | |
| `default_sound_scope` | Select `Urgent Only\nAction Items\nEverything` | Action Items | |
| `default_tone` | Select (tone ids from `tones.json`) | first standard tone | |
| `default_volume` | Int | 60 | 0–100, validated |
| `urgent_tone`, `immediate_tone`, `reminder_tone` | Select | from `tones.json` roles | organisation-wide |
| `reminder_interval_hours` | Float | 2 | 0 disables reminders; min 0.25 otherwise |
| `coalesce_seconds` | Int | 10 | 1–120 |
| `heartbeat_seconds` | Int | 300 | 60–3600 |
| `summary_cache_ttl` | Int | 60 | seconds, 5–600 |
| `page_size` | Int | 10 | 5–50 |
| `hide_standard_bell` | Check | 0 | CSS-only, stock v15 navbar selector |

Permissions: `System Manager`, `Attention Manager` read/write. Read through
`frappe.get_cached_doc`. The four tone selects list every id in `tones.json`. Frappe stores a
Single's defaults once, at install (`frappe.installer.init_singles`); `after_migrate`
(`install.py`) stores the default of every field that still has no stored value, so a field added
by a later release does not read as empty on existing sites. The role `Attention Manager` ships
as a fixture.

### 3.2 `Attention Source` (name = `key`) [FR-SRC-01..03]

| Field | Type | Notes |
|---|---|---|
| `key` | Data, unique, set only once, `autoname: field:key` | `app.identifier`; `^[a-z0-9_]+(\.[a-z0-9_]+)+$` |
| `label` | Data, translatable | |
| `kind` | Select `Action\nInfo` | |
| `source_type` | Select `DocType Query\nPython` | |
| `enabled` | Check | default 1 |
| `sort_order` | Int | ascending |
| `is_system` | Check, read-only | set for hook-declared sources |
| `app` | Data, read-only | declaring app |
| `hook_label` | Data, hidden, read-only | label as last declared in the hooks; the sync updates `label` only while the two are equal, so an admin's relabel sticks |
| `icon` | Data | name from the bundled icon set |
| `list_route` | Data | optional "view all" route, must start with `/app/` |
| DocType Query section | | visible when `source_type = DocType Query` |
| `reference_doctype` | Link DocType | |
| `filters_json` | Code (JSON) | list of `[field, operator, value]` |
| `title_field`, `from_field`, `date_field`, `priority_field`, `due_field`, `status_field` | Data | `title_field` and `date_field` required |
| `priority_map_json` | Code (JSON) | `{ "<field value>": "urgent" \| "immediate" \| "normal" }` |
| `route_field`, `route_doctype_field`, `route_name_field` | Data | optional, from the hook's `route_fields` (§4.5): a field holding a desk route, and a pair of fields naming the document to open instead of the row |
| `recipient_fields` | Small Text | comma-separated fieldnames holding a user id |
| Python section | | read-only, filled from hooks |
| `get_count`, `get_items`, `get_recipients` | Data | dotted paths |
| `watch_doctypes` | Small Text | comma-separated |
| Targeting | | empty = all desk users |
| `roles` | Table MultiSelect → `Attention Source Role` (`role` Link Role) | |
| `user_groups` | Table MultiSelect → `Attention Source User Group` (`user_group` Link User Group) | |

Validation (controller): key format; `Python` type only when `is_system` (reject otherwise)
[FR-SRC-03 AC2]; `reference_doctype` exists and is not a child table or Single; every mapped
field exists in its meta (or is a standard field); `filters_json` parses, uses allowed
operators (`=, !=, >, <, >=, <=, in, not in, like, is`), references existing fields, and
placeholders are only `{user}`, `{today}`; `list_route` starts with `/app/`. System sources
reject edits to definition fields. Permissions: `System Manager`, `Attention Manager`.

Also enforced: `priority_map_json` is an object whose values are `urgent`, `immediate` or `normal`
and needs `priority_field`; `route_doctype_field` and `route_name_field` are set together;
`in`/`not in` take a list, other operators a single value, `is` takes
`set` or `not set`; a `DocType Query` source leaves the Python fields empty; a `Python` source
names `get_count` and `get_items`. Definition fields are everything except `enabled`,
`sort_order`, `label`, `roles` and `user_groups` [FR-SRC-01 AC2]. Saving or deleting a source,
or saving the settings, clears the visibility cache (§4.6).

Origin: Frappe does not enforce read-only fields on the server, so the controller does. Only a
save with `doc.flags.from_hooks = True` may set or clear `is_system`, set `app`, or change the
definition of a system source; the registry sync (§4.6) is the only code that sets this flag. A
client cannot send it: `flags` is a reserved key that `frappe.get_doc` ignores.

### 3.3 `Attention User Preference` (name = user) [FR-SET-02]

`user` (Link User, unique), `sound_scope` (Select, empty or one of the settings scopes), `tone`
(Select, empty or a tone id), `volume` (Data: empty or a whole number 0–100, because an Int column
cannot be empty), `dnd_until` (Datetime),
`auto_open_on_login` (Select `Default\nYes\nNo`), `display_mode` (Select `Default\nDialog\nPanel\nDrawer`),
`launcher_collapsed` (Check), `watermarks` (JSON: `{source_key: iso_datetime}`),
`last_auto_open_sid` (Data, hash of the session id). Empty/`Default` = inherit settings.
No desk permissions except `System Manager` read; all access goes through `engine/preferences.py`
with explicit own-user checks. Created lazily on first write.

### 3.4 Release 0.2

`Attention Announcement` (title, body Text Editor sanitised on save, priority, `valid_from`,
`valid_to`, audience: `all_users` Check / roles / user groups, `requires_acknowledgement`,
`published` Check) and `Attention Announcement Receipt` (announcement, user, `acknowledged_at`;
unique on (announcement, user)). Announcements are exposed through a built-in python source.

## 4. Source contract v1 [FR-SRC-01..06]

`CONTRACT_VERSION = 1` lives in `engine/contract.py`. Changing a shape in a breaking way means
contract v2 with v1 still accepted.

### 4.1 Hook

A consumer app adds to its own `hooks.py` (plain data, no import of this app):

```python
attention_sources = [
    {   # declarative
        "key": "my_app.open_requests",
        "contract_version": 1,
        "label": "Open Requests",          # English; translated by the consumer app
        "kind": "action",                  # "action" | "info"
        "type": "doctype_query",
        "doctype": "My Request",
        "filters": [["status", "=", "Open"], ["assigned_to", "=", "{user}"]],
        "fields": {"title": "subject", "from": "owner", "date": "modified",
                   "priority": "priority", "due": "due_date", "status": "status"},
        "priority_map": {"High": "urgent", "Critical": "immediate"},
        "recipient_fields": ["assigned_to"],
        "list_route": "/app/my-request?status=Open",
    },
    {   # python
        "key": "my_app.unit_inbox",
        "contract_version": 1,
        "label": "Unit Inbox",
        "kind": "action",
        "type": "python",
        "get_count": "my_app.attention.unit_inbox_count",
        "get_items": "my_app.attention.unit_inbox_items",
        "get_recipients": "my_app.attention.unit_inbox_recipients",   # optional
        "watch_doctypes": ["My Telegram", "My Telegram Recipient"],   # optional
        "list_route": "/app/my-inbox",
    },
]
```

### 4.2 Python callables

```python
def get_count(user: str) -> int | dict: ...
    # int, or {"count": int, "urgent": int, "immediate": int, "overdue": int,
    #          "latest": datetime | None, "new_since": int}
    # Called with frappe.session.user == user. May accept an optional keyword
    # `since: datetime | None` (the user's watermark) to compute "new_since".

def get_items(user: str, start: int, page_length: int) -> list[dict]: ...
    # Already sorted by the source; at most page_length items.

def get_recipients(doc) -> list[str]: ...
    # User ids to nudge when `doc` (of a watched DocType) changes. Runs in the
    # actor's request, so it must not depend on frappe.session.user.
```

The engine inspects the signature once and passes `since` only if accepted.

`contract.validate_source_def` checks the shape of a hook entry: a supported `contract_version`
(an `int`), the key format, `type`, `kind`, `label`, the optional `icon` and `list_route`, the
keys each type needs, and the types of their values. A key that is not part of the entry's type
(a misspelt `filter`, a python key in a declarative entry) is rejected rather than ignored, because
an ignored filter would widen the query. The filters, the priority map and the fieldnames are
checked against the DocType by the `Attention Source` controller when the sync saves the entry,
so those rules exist once; `validate_source_def` only checks that filters and the priority map hold
values JSON can store (text, numbers, booleans, None, lists, dicts). A `date` or a `set` is
rejected, not converted, so the entry is skipped like any other instead of stopping the sync.

### 4.3 Item

| Key | Required | Type | Notes |
|---|---|---|---|
| `id` | yes | str | unique within the source |
| `title` | yes | str | plain text; HTML is stripped by the engine |
| `route` | yes* | str | desk route beginning with `/app/` |
| `reference_doctype`, `reference_name` | yes* | str | alternative to `route`; the engine builds the form route |
| `type_label` | no | str | short label shown as a badge |
| `from_label` | no | str | display name; or `from_user` (user id, resolved to full name) |
| `date` | no | datetime | arrival/creation time |
| `priority` | no | `normal` \| `urgent` \| `immediate` | default `normal` |
| `due` | no | date/datetime | overdue is computed by the engine: `due < now` |
| `status_label` | no | str | |
| `status_color` | no | `gray` \| `blue` \| `green` \| `orange` \| `red` | default `gray` |

\* one of the two. `engine/contract.py::normalize_item` validates, strips HTML, truncates
`title` to 200 chars, coerces dates to ISO strings and drops invalid items with a single
`frappe.logger("attention_center")` warning per source per request.

Normalised items carry exactly the keys above (with `from_label` resolved, `route` built from the
reference when needed) plus `overdue`; anything else a source returns is dropped. Items without a
valid `id`, `title` or route, and repeated ids, are dropped (`normalize_items`, one warning with
the source key and counts). An invalid optional value falls back to its default instead of
dropping the item, so the user never loses an item that can still be opened. A `due` date is
overdue from the next day on; a `due` datetime once it has passed. Datetimes with a time zone
are converted to the system time zone. Date strings are accepted in ISO form only.

### 4.4 Declarative executor (`engine/doctype_query.py`)

- Resolve placeholders in filter values (`{user}`, `{today}`) — value-level replacement only, never string-built SQL. One pass, so a user id containing `{today}` is not resolved again.
- Count pass: `frappe.get_list(doctype, filters=…, fields=[name, date, priority, due], order_by="<date_field> desc, name desc", limit_page_length=COUNT_CAP + 1)` with `COUNT_CAP = 99` (in `contract.py`). From these rows derive `count`, `urgent`, `immediate`, `overdue`, `latest`, `new_since`; `contract.normalize_count` caps every number at 99 and sets `capped` from 100 rows on, for declarative and python sources alike. One query per source. An urgent or overdue row older than the newest 100 is not counted.
- `new_since` counts rows whose date is after the user's watermark; a date-only field counts from midnight. Without a watermark every row is new.
- Priority: `priority_map` maps the field's values; without a map the field must hold `urgent`, `immediate` or `normal` itself. Any other value is `normal`.
- Items pass: the same filters and order, the mapped fields. The newest `COUNT_CAP + 1` rows (the rows the count covers) are sorted in Python by overdue, then priority; the sort is stable, so newest stays first within a class [FR-API-02]. A page reaching past those rows fetches the rest with `limit_start` in date order only: beyond 100 pending rows the tail is ordered by date. The `name` tie-breaker keeps the window and the tail from overlapping.
- Every query runs under a statement timeout of `TIME_BUDGET_SECONDS` (2 s): `frappe.db.set_execution_timeout`, then back to `frappe.database.database.get_query_execution_timeout()`, the value Frappe sets when it connects. A stopped query fails the source like any exception [NFR-PERF-03].
- `frappe.get_list` applies role permissions, user permissions and `permission_query_conditions` [FR-PERM-02], and drops fields above the user's permission level (a mapped field can then be missing). Never use `frappe.get_all`, `frappe.db.sql`, or `ignore_permissions` in a source.
- An item opens the row's form, unless the route fields say otherwise (§4.5).
- Titles come from `title_field`; `from_field` values go through `frappe.utils.get_fullname` (`from_user`), which resolves user ids and returns any other value unchanged. `status_label` is the translated status value. The executor returns raw items; the runner normalises them.

### 4.5 Built-in sources (`sources/`)

| Key | Kind | Definition |
|---|---|---|
| `attention_center.approvals` | action | Python. `frappe.get_list("Workflow Action", filters={"status": "Open"}, fields=[name, reference_doctype, reference_name, workflow_state, creation], limit COUNT_CAP+1)` (its own `permission_query_conditions` restrict rows to the user's roles), then keep rows where `frappe.has_permission(reference_doctype, "read", reference_name)` is true, de-duplicated by (doctype, name). Title: the document's title field value, falling back to the name. `type_label`: translated DocType. `status_label`: `workflow_state`. Recipients: users holding any permitted role, capped at 200; above the cap, broadcast (see §6) |
| `attention_center.assignments` | action | Declarative on `ToDo`: `status = Open`, `allocated_to = {user}`; title = `description` (HTML stripped), from = `assigned_by`, date = `creation`, due = `date`, priority map `{"High": "urgent"}`, recipient field `allocated_to`. Route: the reference document when `reference_type`/`reference_name` are set, else the ToDo |
| `attention_center.notifications` | info | Declarative on `Notification Log`: `for_user = {user}`, `read = 0`; title = `subject` (HTML stripped), from = `from_user`, date = `creation`, recipient field `for_user`. Route: the log's `link`, else its reference document |

The route exception for ToDo and Notification Log is expressed as an optional
`route_fields: {"route": "...", "doctype": "...", "name": "..."}` mapping in the declarative
definition, stored in `route_field`, `route_doctype_field` and `route_name_field`. An item opens the
value of `route` when it is a desk route (`/app/…`), else the document named by `doctype` and `name`
when the row sets both, else the row itself. Assignments map `doctype`/`name` to
`reference_type`/`reference_name`; notifications map `route` to `link` and `doctype`/`name` to
`document_type`/`document_name`.

Approvals details: one item per document, the newest open action's name as `id` and its `creation`
as `date`. The title is the title field (`meta.get_title_field()`) only when the user may read that
field's permission level, else the document name. An action whose document or DocType is gone is
skipped: the DocType is checked with `frappe.db.exists` before `get_doc`, which raises `ImportError`
for a deleted DocType, and the "not found" message Frappe queues for a deleted document is dropped. The hook entry declares no
`get_recipients`: a python source's recipients are a plain list, which cannot ask for the broadcast
above the cap, so `engine/recipients.py` computes the role holders (§6). It declares
`watch_doctypes: ["Workflow Action"]`, so its changes reach the realtime handler; the registry also
routes the DocTypes of the active workflows to it (§6).

"View all" routes: approvals `/app/workflow-action?status=Open`, assignments
`/app/todo?status=Open`, notifications `/app/notification-log?read=0`. The definitions live in
`sources/builtin.py`; this app's `hooks.py` declares them in `attention_sources` like any consumer app.

### 4.6 Registry and visibility (`engine/registry.py`)

- `load_hook_sources()` reads `frappe.get_hooks("attention_sources", app_name=app)` for each installed app (so the declaring app is known), validates each entry (`contract.validate_source_def`), skips bad ones with one log line each (level ERROR, Frappe's default production level). A duplicate key is skipped; the app installed first keeps it.
- `sync_sources()` (called from `after_migrate` and `after_install`) upserts hook sources into `Attention Source` with `is_system = 1`, preserving admin-owned fields (`enabled`, `sort_order`, `label` if changed by admin, targeting), and disables system sources whose app/hook vanished. It writes only when a value differs, so a repeated migrate changes nothing. An entry the controller rejects (unknown DocType or field, bad filter) is logged and skipped like a vanished one: a system source whose new definition is rejected is disabled and keeps its last valid definition. A disabled system source stays disabled when its entry comes back; enabling it again is an admin's act. A hook entry whose key is already used by a source created in the desk is skipped and the desk source left untouched.
- `get_visible_sources(user)` returns enabled sources, ordered by `sort_order` then creation, where targeting matches (`frappe.get_roles(user)`, `User Group Member`) and — for declarative ones — `frappe.has_permission(doctype, "read", user=user)`. Targeting is a union: no roles and no groups means every desk user, otherwise holding any listed role or belonging to any listed group is enough. A declarative source whose DocType no longer exists (its app was removed before the next migrate) is hidden instead of failing. Cached per user in `frappe.cache` (`attention_center:visible`), cleared on source/settings save and on role or user-group changes (doc events on `User`, `User Group`, `Has Role` are too broad: clear the whole hash when `Attention Source` or settings change, and give the per-user entry a 5-minute TTL). The hash is cleared at once and again after commit, so a request that read the old rows in between cannot keep them for five minutes.

### 4.7 Runner (`engine/runner.py`)

`run_count(source, user, since=None)` and `run_items(source, user, start, page_length)`, where `user` is the session user and `since` their watermark for the source:
- `run_count` returns `{"state": "ok", count, capped, urgent, immediate, overdue, latest (ISO text), new_since}`, or the same keys with zeros and `"state": "error"`; `run_items` returns `{"state": "ok" | "error", "items": [...]}` with at most `page_length` normalised items.
- wrap each call in `try/except Exception`, measure duration, and convert failures into the error state; log key, user, duration, exception type at ERROR [FR-SRC-05, NFR-PRIV-01]. A `ContractError` adds its own message, which quotes no content. Messages the failed source queued with `frappe.msgprint`/`frappe.throw` are dropped, so a background refresh never opens a dialog.
- soft time budget: a source slower than `TIME_BUDGET_SECONDS` (2 s) is logged as slow (WARNING); python sources that raise or return invalid shapes are errors. (No thread-based hard timeout in 0.1: it is unsafe with the DB connection. Declarative queries run under a statement timeout, see §4.4.)
- cache `run_count` results per (source, user): `frappe.cache.hset(f"attention_center:count:{key}", user, {stored_at, since, result})`; an entry older than `summary_cache_ttl` or stored for another watermark is recomputed [FR-API-01 AC1]. Failed results are cached too, so a broken or slow source runs at most once per user per TTL.

## 5. Server API (`attention_center/api.py`)

All are `@frappe.whitelist()` (POST for mutations), require a logged-in desk user (`user_type`
System User: Guest and website users get `frappe.PermissionError`), and take no user argument
[FR-PERM-01]. While the settings disable the app no source is visible: the summary is empty and
`get_items` / `mark_seen(source)` refuse every key.

| Method | Returns / effect |
|---|---|
| `get_summary()` | `{generated_at, sources: [{key, label, kind, icon, count, capped, urgent, immediate, overdue, latest, new_since, state, list_route}], totals: {action, attention, info_new}}`; `kind` is `action` or `info`, `label` translated with the `Attention Source` context |
| `get_items(source: str, start: int = 0, page_length: int \| None = None)` | `{state, items: [...], has_more: bool}` (`state` as from `run_items`, so a tab can show its error); `frappe.PermissionError` if the source is not visible, with the same message for a missing key; `start` ≥ 0; `page_length` defaults to `page_size` and is clamped to 1..50; `has_more` comes from asking the source for one item more |
| `mark_seen(source: str \| None = None)` | sets the watermark of the source, or of every visible source, to now |
| `get_preferences()` / `set_preferences(prefs: dict \| str)` | effective preferences / validated update of own preferences (below) |
| `note_auto_opened()` | stores the SHA-256 of the current session id; `should_auto_open` is true until it is called in the login session |
| `test_source(source: str)` | System Manager or Attention Manager (checked with `frappe.get_roles`): `{count: <run_count result>, items: <run_items result, first 5>, duration_ms}` for the caller, for any source, enabled or not; the caller's cached count is dropped first |

`totals.attention` = sum over action sources of `urgent + immediate + overdue` (an item that is
both urgent and overdue may be counted twice in 0.1; acceptable and documented). `totals.action`
sums `count` over action sources, `totals.info_new` sums `new_since` over info sources.

Preferences (`engine/preferences.py`, every function acts on the session user's own row) use the
DocType's own values. Effective preferences: `{display_mode, auto_open_on_login: bool,
sound_scope, tone, volume: int, dnd_until: ISO text | null (null once passed), launcher_collapsed:
bool}`. `set_preferences` changes only the names it is given, takes the object or its JSON text
(`frappe.call` sends objects as JSON text) and rejects any other name (`watermarks`,
`last_auto_open_sid`, `user`, …). Values: `sound_scope` and `tone` take `""` to inherit, `tone`
only a `standard` tone of `tones.json`; `volume` `""`/`None` or 0–100; `auto_open_on_login` and
`display_mode` take `Default` to inherit; `dnd_until` ISO date and time (an offset is converted
to the system time zone) or empty; `launcher_collapsed` true/false or 0/1. Watermarks are naive
system-time ISO text per source key. The row is created on the first write; a first write that
loses the race to create it applies to the row the other request created.

`boot.py::extend_bootinfo(bootinfo)` adds `bootinfo.attention_center = {enabled, version,
settings: {hide_standard_bell, urgent_tone, immediate_tone, reminder_tone, reminder_interval_hours,
coalesce_seconds, heartbeat_seconds, page_size}, preferences: {…effective…}, should_auto_open: bool,
tones: [{id, role, label (translated), url}]}`, or `{enabled: False}` when the app is disabled or
the user is not a desk user. It must be cheap (cached settings + one preference read, no source
runs) and never raise: wrap in try/except and return `{enabled: False}` on failure, logging the
user and the exception type only [NFR-PERF-02, NFR-REL-01].

## 6. Realtime (`engine/realtime.py`, `engine/recipients.py`) [FR-RT-01..03]

- `hooks.py`: `doc_events = {"*": {"on_change": "…realtime.on_doc_event", "on_trash": "…realtime.on_doc_event"}}`. `on_change` fires after insert, save, submit, cancel and `db_set` (confirmed in Frappe 15.126, `frappe/model/document.py`: `run_post_save_methods` and `db_set`). Document events run for the parent document only, never for its child rows, so a child table listed in `watch_doctypes` never fires.
- `on_doc_event(doc, method)` first looks up `doc.doctype` in the watch map `{doctype: [source entries]}` (`registry.get_watch_map()`) built from the enabled sources: declarative `reference_doctype`, python `watch_doctypes`. The approvals hook entry declares `watch_doctypes: ["Workflow Action"]`, and the enabled approvals source also watches the `document_type` of every active `Workflow` (below). Unwatched → return immediately [FR-RT-01 AC1]. Skip entirely during install/migrate/import (`frappe.flags.in_install`, `in_migrate`, `in_import`). The handler never raises: a failure is logged with the DocType and the exception type, and the user's save goes on.
- The watch map is kept in `frappe.cache` (`attention_center:watched`), which also holds it in `frappe.local.cache` for the rest of the request: an unwatched DocType costs a dict lookup and no query. It is cleared with the visibility cache (source save or delete, settings save, sync), when a `Workflow` is saved (`on_change`) or deleted (`after_delete`, because in `on_trash` the row still exists and the `*` handler that runs next would cache it again), and recomputed after 5 minutes at the latest, like the visible sources (§4.6). A per-process map could not be cleared in the other workers when a source changes.
- Recipients (`recipients.get_recipients(source, doc)`): declarative → current and previous values of `recipient_fields` (`doc.get_doc_before_save()`), so a reassignment nudges both users; python → `get_recipients(doc)` in try/except (the messages it queued are dropped; a failure, or a result that is not a list, is logged with the key, the DocType and the exception type); approvals → enabled users holding any of the Workflow Action's `permitted_roles` (`Has Role` query, capped). `method` (the document event) is passed along for the next rule.
- Unknown or oversized audience, nudged by broadcast: a declarative source without `recipient_fields`; a python source without `get_recipients`, or whose `get_recipients` failed; an action open to a role Frappe gives without a `Has Role` row (`All`, `Desk User`, `Guest`); more than `AUDIENCE_CAP` (200) users.
- Collect `(user, source_key)` pairs and the keys to broadcast in `frappe.local.attention_center_nudges` and register one `frappe.db.after_commit` callback per transaction (with an `after_rollback` callback that discards them) that: invalidates the count cache for those pairs, then publishes per user `frappe.publish_realtime("attention_center_nudge", {"sources": [...], "actor": frappe.session.user}, user=user)` [FR-RT-01 AC2, FR-PERM-05]. The callback never raises: the changes are already committed.
- Broadcast: delete the whole count hash for the source and publish once to the site room (no `user`; Frappe's socket server joins only System Users to it) with `{"sources": [...], "broadcast": true}`; clients then wait a random 0–5 s before refetching. A broadcast names no actor, and a source broadcast in a transaction is left out of that transaction's user nudges.
- Frappe completes and deletes Workflow Actions with queries (`update_completed_workflow_actions`, `clear_workflow_actions`), which raise no document event, from its own `*` hooks, which run before this app's. So a document under an active workflow is watched by approvals: when a save moves it out of a workflow state (`get_doc_before_save()` holds another state) or it is deleted (`on_trash`: its current state), the enabled holders of the roles allowed on the transitions out of that state are nudged with the same query, cap and broadcast rule. The roles come from the cached Workflow definition (`get_workflow_name`, `frappe.get_cached_doc`), not from the action rows, which are already completed or gone; transition conditions are not evaluated, so the audience may be larger than the completed action's, never smaller. An insert, or a save that keeps the state, nudges no approver from the document: the action it creates fires its own insert. `frappe.delete_doc` also runs `on_change` after `on_trash`; that pass adds nothing, since a deleted document has no previous version.
- Known staleness, bounded by `summary_cache_ttl`: Frappe's bell marks Notification Logs read with `frappe.db.set_value` (`mark_as_read`, `mark_all_as_read`), which raises no event, so the reader's notifications count stays cached until it expires (fixing it would mean overriding core; the client may refetch after the bell is used). A request that computed a count from the snapshot before a commit can store it just after the callback dropped it, which keeps that value for one TTL. A change undone with `rollback(save_point=…)` still sends its (content-free) nudge.
- `nudge(users: list[str], source_key: str)` is the public helper for consumer apps [FR-RT-03]. It raises `frappe.ValidationError` for a key that names no `Attention Source` and for users that are not a list of user ids, sends after the commit like document nudges, and broadcasts above the cap. Consumer-side call pattern (documented in the provider guide): `if "attention_center" in frappe.get_installed_apps(): frappe.get_attr("attention_center.engine.realtime.nudge")(users, key)`.

## 7. Client architecture

Vanilla ES modules bundled by Frappe's esbuild (`bench build --app attention_center`). No UI
framework. Everything renders into one host element with an open shadow root.

```
public/js/attention_center/
  index.js            boot: guards, host element, launcher, wiring       (launcher bundle)
  store.js            tiny observable state {summary, prefs, ui}
  api.js              frappe.call wrappers, request de-duplication
  realtime.js         nudge listener, visibility/reconnect/heartbeat refresh
  alerts/policy.js    PURE: (prevSummary, nextSummary, prefs, now, actor) -> alert decisions
  alerts/coalesce.js  PURE: burst merging
  alerts/sound.js     tone playback, unlock, volume, DND
  alerts/tabs.js      cross-tab "who plays" coordination
  alerts/reminder.js  periodic reminder scheduling
  ui/styles.js        CSS text (logical properties only), tokens, dark mode
  ui/icons.js         inline SVG icons used by the UI
  ui/launcher.js  ui/toast.js
  ui/window.js  ui/tabs.js  ui/table.js  ui/settings.js   (window bundle, lazy)
  util/dom.js  util/time.js  util/escape.js
tests/js/             node --test unit tests for the PURE modules and coordination logic
```

### 7.1 Boot and isolation [FR-UI-05, NFR-REL-01]

- `attention_center.bundle.js` is listed in `app_include_js`. On `$(document).on("app_ready")` (or immediately if the desk is already up) it checks `frappe.boot.attention_center?.enabled` and `frappe.session.user !== "Guest"`, then creates `<div id="attention-center-root">` on `document.body`, attaches `mode: "open"` shadow root, and adopts the stylesheet (`CSSStyleSheet` + `adoptedStyleSheets`, falling back to a `<style>` element).
- The whole boot is inside `try { … } catch (e) { console.error("[attention_center]", e); }`. Event handlers and timers are wrapped by one `safe(fn)` helper.
- CSS uses logical properties only (`inset-inline-end`, `margin-inline-start`, …) so the same sheet serves RTL and LTR. The root element copies `dir` and `lang` from `document.documentElement` and observes `data-theme` for dark mode. Fonts inherit from the page.
- Icons are inline SVG from `ui/icons.js` (Frappe's sprite `<use>` references do not resolve inside a shadow tree).
- z-index: launcher and toasts 1020; our dialog overlay 1030 — below Bootstrap/Frappe modals (1040/1050) so system dialogs always win [FR-UI-01 AC1].
- The window bundle is loaded with `frappe.require("attention_center_window.bundle.js")` on first open [NFR-PERF-02].

### 7.2 Launcher, window, modes [FR-UI-01..04, 06..08]

- One content component (tabs + table/stacked rows + pagination + settings view) and three containers selected by a `data-mode` attribute: `dialog` (centred, overlay, focus trap), `panel` (anchored above the launcher, 380 px), `drawer` (inline-end edge, full height, 420 px). `panel` and `drawer` always use the stacked-row layout; `dialog` uses the table at ≥ 720 px container width and stacked rows below (container query, with a `ResizeObserver` fallback).
- Navigation: `frappe.set_route` for `/app/...` routes after closing the window. Routes are validated to start with `/app/`; anything else is ignored.
- Keyboard: `Alt+Shift+A` toggles the window (register through `frappe.ui.keys.add_shortcut` when available); `Esc` closes; roving tabindex on tabs; rows are focusable with an explicit "Open" button.
- Live region (`aria-live="polite"`) in the shadow root announces alerts. `prefers-reduced-motion` disables the pulse and slide animations.
- Title counter: prefix `document.title` with `(N) ` and keep it in place across route changes (Frappe rewrites the title on navigation: re-apply on `frappe.router.on("change")` and via a `MutationObserver` on `<title>`).

### 7.3 Refresh loop [FR-RT-02]

`realtime.js` triggers `store.refreshSummary()` (debounced 1.5 s, de-duplicated) on:
`frappe.realtime.on("attention_center_nudge")` (plus 0–5 s jitter when `broadcast`),
`visibilitychange` → visible, socket `connect`/`reconnect`, `window` `online`, and a heartbeat
every `heartbeat_seconds` while the document is visible. The first fetch happens after boot, not
during it.

### 7.4 Alerts [FR-ALERT-01..06]

- `alerts/policy.js` is a pure function comparing the previous and next summary: a source whose `count` or `latest` increased produced "new items"; the class of the alert comes from the source kind and the increase in `immediate` / `urgent`. It applies the scope table of FR-ALERT-02, self-suppression (`actor === session user` on the triggering nudge), and Do Not Disturb. The very first summary after page load produces no "new item" alerts (it feeds the login logic instead).
- `alerts/coalesce.js` merges decisions inside `coalesce_seconds` into one toast and one sound of the highest class.
- Login: if `boot.should_auto_open` and effective `auto_open_on_login` and `totals.action > 0`, open the window once, call `note_auto_opened()`. The summary line is the sum of `new_since` over action sources.
- Reminder: a one-minute timer checks `totals.attention > 0` and `now - lastReminderAt ≥ interval`; `lastReminderAt` lives in `localStorage` (`attention_center:last_reminder`) so all tabs share it.

### 7.5 Sound [FR-SND-01..04]

- `public/sounds/tones.json` lists tones: `{id, file, role: "standard" | "urgent" | "immediate" | "reminder", label}`. Files are produced by `scripts/sounds/generate_tones.py`; never hand-edit or replace them with third-party audio.
- Playback uses `HTMLAudioElement` objects created lazily (`new Audio(url)`), with `volume = pref.volume / 100`. `play()` rejection with `NotAllowedError` sets `audioLocked = true`, triggers the pulse and the one-time hint, and installs one-shot `pointerdown`/`keydown` listeners that unlock by playing a muted tone.
- Mute sources, in order: `frappe.boot.user.mute_sounds`, DND active, scope rules.
- Cross-tab single playback (`alerts/tabs.js`): every alert gets an id (source keys + time bucket). A tab that wants to play posts `claim:<id>` on `BroadcastChannel("attention_center")` and writes `attention_center:claim:<id>` to `localStorage` with its random tab id, waits 120 ms + random 0–80 ms, and plays only if the stored claim is its own. Visible tabs wait 0 ms extra so they win. No Web Locks, no service worker, no Notification API: the production origin is plain HTTP [NFR-COMP-02].

### 7.6 Settings UI [FR-SET-02, FR-UI-03]

A settings view inside the window edits the user's preferences through `set_preferences`.
Admin configuration uses the standard desk forms of the two DocTypes plus a small form script
for `Attention Source` (field visibility by type, "Test for my user").

## 8. Permission model summary

| Layer | Mechanism |
|---|---|
| Endpoint | session user only; Guest and website users rejected; the manager endpoint checks `frappe.get_roles()` for System Manager or Attention Manager (`frappe.only_for` lets everyone through while tests run, so a test could not prove it) |
| Source visibility | enabled ∧ targeting ∧ DocType read permission (declarative) |
| Rows | `frappe.get_list` (declarative), per-document `frappe.has_permission` (approvals), the source's own logic (python) |
| Realtime | content-free payload, user rooms, after commit |
| Storage | preferences readable/writable only by their owner through the API |
| Client | all text escaped; routes restricted to `/app/` |

## 9. Internationalisation

English source strings wrapped with `_()` / `__()`. No string concatenation or template literals
inside the translation call; use placeholders (`__("{0} new items", [n])`). `translations/ar.csv`
holds simple, familiar Arabic. A backend test extracts every `_()`/`__()` literal from the app
and fails if one is missing from `ar.csv` [NFR-I18N-01]. Dates and "x ago" text use Frappe's
client utilities so they follow the user's locale.

## 10. Test strategy [NFR-MAINT-01]

- **Backend** (`bench --site <site> run-tests --app attention_center`): `FrappeTestCase` from `frappe.tests.utils` (Frappe 15). Each test creates its own users/roles/documents and cleans up via rollback. Mandatory coverage: source-definition validation; declarative executor (placeholders, mapping, caps, ordering); permission filtering with role permissions, a User Permission, and a `permission_query_conditions` fixture DocType created in the test; approvals with "role but no read permission"; targeting narrowing; fault isolation (a raising python source); cache TTL and invalidation; recipients and single nudge per request (`frappe.publish_realtime` patched); API input validation and "cannot read another user's data"; preferences validation; translation completeness.
- **Client pure logic**: `node --test tests/js` for policy, coalescing, tab coordination (fake channel/storage/clock), reminder scheduling, escaping and route validation. No browser needed.
- **UI smoke** (from M6): Playwright against the sandbox/CI site: launcher renders, window opens in three modes, RTL/LTR screenshots, keyboard open/close. Kept small.
- Tests must be able to fail: no assertion-free tests, no mocking of the unit under test, no reliance on old data in the site.
- `scripts/ci/run_tests.sh` is the single entry point used by CI and by agents locally.

## 11. Performance notes

One capped query per source per user per TTL; nudges invalidate precisely. The approvals source
performs up to 100 permission checks per recompute — acceptable behind the cache; keep it out of
`extend_bootinfo`. The doc-event hook must stay O(1) for unwatched DocTypes; measure it in a test
with a counter on the slow path.

## 12. Compatibility notes

- Themes may replace the desk shell and ship aggressive global CSS (Tailwind preflight, hundreds of `!important` rules) and their own modal scripts that act on any `.modal` element. Hence Shadow DOM, no Bootstrap classes, no element with class `modal`, `collapse`, `hidden` or `fixed` in our light-DOM host.
- Themes with a fixed sidebar occupy the inline-start side and bottom-start corner; the launcher lives at the inline-end corner.
- Frappe 16 moves notifications into a sidebar and changes `Notification Log.type` to a Link; we touch neither.
