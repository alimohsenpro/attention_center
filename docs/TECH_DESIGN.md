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
  attention_center/doctype/           DocTypes (module "Attention Center") with their form scripts
  attention_center/workspace/         the managers' workspace
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
| `hide_standard_bell` | Check | 0 | CSS-only, stock v15 navbar selector (§7.7) |

Permissions: `System Manager`, `Attention Manager` read/write. Read through
`frappe.get_cached_doc`. The four tone selects list every id in `tones.json`; the form shows them with
their labels (§7.7). Frappe stores a
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
- Every query runs under the runner's statement timeout of `TIME_BUDGET_SECONDS` (2 s, §4.7); a stopped query fails the source like any exception [NFR-PERF-03].
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
- time budget: every call of a source, declarative or python, runs under a statement timeout of `TIME_BUDGET_SECONDS` (2 s): `frappe.db.set_execution_timeout`, then back to `frappe.database.database.get_query_execution_timeout()`, the value Frappe sets when it connects. A stopped statement fails the source like any exception [NFR-PERF-03]. A source slower than the budget in all (many quick statements, or Python work) is logged as slow (WARNING); python sources that raise or return invalid shapes are errors. (No thread-based hard timeout in 0.1: it is unsafe with the DB connection.)
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
  store.js            tiny observable state {summary, prefs, ui}; summary refresh, one request at a time
  api.js              server calls over fetch (no core dialogs), request de-duplication
  realtime.js         nudge listener, visibility/reconnect/heartbeat refresh
  alerts/policy.js    PURE: (prevSummary, nextSummary, prefs, now, actor) -> alert decisions
  alerts/coalesce.js  PURE: burst merging
  alerts/sound.js     tone playback, unlock, volume, DND
  alerts/tabs.js      cross-tab "who plays" coordination
  alerts/reminder.js  periodic reminder scheduling
  alerts/login.js     PURE: the login auto-open decision and its "new since you last looked" count
  ui/styles.js        CSS text (logical properties only), tokens, dark mode
  ui/icons.js         inline SVG icons used by the UI
  ui/launcher.js  ui/toast.js
  ui/window.js  ui/tabs.js  ui/table.js  ui/settings.js   (window bundle, lazy)
  ui/window_styles.js CSS text of the window, added to the shadow root by the window bundle
  util/feed.js        PURE: the items of a tab page by page; the "All" tab's merge of the action sources
  util/window_tabs.js PURE: summary -> the window's tabs (sources, counter, attention, unseen, "view all")
  util/keys.js        PURE: roving focus in the tab list, focus-trap wrap-around, the keys the window keeps from the desk
  util/guard.js       PURE: the guard every entry point runs through (§7.1)
  util/badge.js       PURE: summary -> launcher count text ("99+"), attention accent, unseen dot
  util/bell.js        the <style> that hides the stock navbar bell when the settings ask for it (§7.7)
  util/title.js       "(N) " tab-title counter: PURE retitle + a <title> observer
  util/route.js  util/escape.js   PURE: desk-route validation and set_route arguments, HTML escaping
  util/dom.js         stylesheet adoption into the shadow root, element and button helpers
  util/time.js        PURE: Do Not Disturb times ("for 1 hour", "until the end of the day") on naive time text
  util/settings.js    PURE: a settings change applied at once and stored, with its saving / saved / failed state
  util/share_prefs.js the preferences kept in step across the user's tabs (BroadcastChannel)
tests/js/             node --test unit tests for the PURE modules and coordination logic; the root
                      package.json only declares "type": "module" so that Node loads the client modules
```

### 7.1 Boot and isolation [FR-UI-05, NFR-REL-01]

- `attention_center.bundle.js` is listed in `app_include_js`. On `$(document).on("app_ready")` (or immediately if the desk is already up) it checks `frappe.boot.attention_center?.enabled` and `frappe.session.user !== "Guest"`, then creates `<div id="attention-center-root">` on `document.body`, attaches `mode: "open"` shadow root, and adopts the stylesheet (`CSSStyleSheet` + `adoptedStyleSheets`, falling back to a `<style>` element). The sheet resets the host with `:host { all: initial !important }`, so page CSS cannot give it a box, and declares the tokens as custom properties on `:host`, which page CSS can still override.
- The boot and every event handler, observer and timer run through one guard (`util/guard.js`, `run(fn)` / `safe(fn)`): the first exception or rejected promise is logged with `console.error("[attention_center]", e)`, runs the registered cleanups (host removed, observers disconnected, title counter removed) and turns the client off for the page load. A failed request is not a failure of the client: the launcher keeps what it shows.
- Requests go through `fetch`, not `frappe.call` (`api.js`, `createTransport`): a same-origin POST of a JSON body to `/api/method/<method>` with the `X-Frappe-CSRF-Token` header, read from `frappe.csrf_token` at each request because the desk renews it when the user logs in again in another tab; any answer other than 2xx rejects, and the caller keeps what it shows. In `frappe.call`, `silent: true` only hides `_server_messages`; its status handlers still act (`frappe/public/js/frappe/request.js`): 404, 502, 504 and 508, and a 403 that carries no server message, open a `msgprint`; 500 plays the error sound and opens the Server Error report; a `QueryTimeoutError` or `QueryDeadlockError` opens a message with the error sound; an offline browser gets a "Connection Lost" alert; a 401 or an answer flagged `session_expired` sends the page to `/login`. Session expiry is left to the desk: a request of this app never redirects or opens a dialog, so the user's next own request is the one that leads to the login page.
- CSS uses logical properties only (`inset-inline-end`, `margin-inline-start`, …) so the same sheet serves RTL and LTR. The root element copies `dir` and `lang` from `document.documentElement` and observes `data-theme` for dark mode. Fonts inherit from the page.
- Icons are inline SVG from `ui/icons.js` (Frappe's sprite `<use>` references do not resolve inside a shadow tree).
- z-index: launcher 1020; our window (the dialog's backdrop, the panel, the drawer) 1030; toasts 1035, over the open window so that a toast stays visible and clickable in every mode (§7.4) — all below Bootstrap/Frappe modals (1040/1050) so system dialogs always win [FR-UI-01 AC1].
- The window bundle is loaded on first open [NFR-PERF-02] by a `<script>` element whose `src` is the bundle's entry in `frappe.boot.assets_json` (the lookup `frappe.require` makes). `frappe.require` itself is not used: in Frappe 15 (`frappe/public/js/frappe/assets.js`) it freezes the desk while it fetches, evaluates the answer whatever its status, and never unfreezes when the request fails, and its promise then never settles. A bundle that does not load is treated like a failed request: the window stays closed and the next click tries again. The window bundle hands its factory over as `window.attention_center_window.createWindow`; the launcher passes it the store, the api, the guard's `safe`, the live region and the page size, so the two bundles share no module instances. The window's CSS travels in its bundle and is added to the shadow root next to the launcher's sheet.

### 7.2 Launcher, window, modes [FR-UI-01..04, 06..08]

- One content component (tabs + table/stacked rows + pagination + settings view) and three containers selected by a `data-mode` attribute on the window's frame, from the effective `display_mode` preference [FR-UI-03]: `dialog` (centred, backdrop, focus trap, `aria-modal`), `panel` (anchored above the launcher, 380 px), `drawer` (inline-end edge, full height, 420 px). The panel and the drawer are non-modal: no backdrop and no focus trap, so the page beside them stays usable; their frame is `display: contents`, so it takes no clicks, and a click on the page leaves them open. The drawer covers the launcher's corner, so the launcher is hidden while the drawer is open and Tab cannot reach it. The window follows every change of `prefs.display_mode` in the store at once, keeping its tab, page and focus; a mode button in the header switches dialog → panel → drawer → dialog (its icon and label name the next mode) and stores the choice through `set_preferences`, like the launcher's collapse.
- Responsive rows [FR-UI-04]: the window is a CSS size container; below 720 px of its width a container query shows each table row as a card (title with the priority at its inline end, then type, source, sender and status with the age and "Open" at the inline end) and wraps the tab strip instead of scrolling it, so nothing scrolls sideways at 360 px. The panel (380 px) and the drawer (420 px) are always that narrow, so they always show cards; the dialog shows the table from 720 px. The cards are the table's own rows restyled, with its header kept for screen readers, so a resize never re-renders. Every browser of NFR-COMP-02 supports size container queries, so there is no script fallback.
- Navigation: `frappe.set_route` for `/app/...` routes after closing the window. Routes are validated to start with `/app/`; anything else is ignored. The route is passed as decoded path segments followed by its query as an object of route options (`util/route.js`, `routeArguments`): given the text `/app/todo?status=Open`, Frappe 15's router encodes the `?` into the last segment. "Open" and "View all" are real links (`href` = the route), so a click with a modifier key or the middle button opens a new browser tab; a plain click navigates in place.
- Tabs [FR-UI-02]: "All" first, then one per action source, then the info sources, in summary order (`util/window_tabs.js`). A tab's counter is the source's `count` (`99+` when capped; "All" shows the launcher's action count), red when the tab holds urgent, immediate or overdue items; an info tab with `new_since > 0` shows a dot with the hidden text "New". The window opens on "All", or on the tab a toast names (`store.ui.tab`, §7.4). A toast clicked while the window is open shows that tab from its first page with items fetched afresh, even when it is already selected: the pages fetched earlier in this opening are dropped and its sources are marked seen again, as on a new opening, because the user asked to see what arrived.
- Items [FR-UI-02, FR-API-02]: a tab's items come page by page from `get_items` (`util/feed.js`). The "All" tab merges the action sources like sorted lists: it takes the next item from whichever source's next item comes first (overdue, then immediate, urgent, normal, then newest) and fetches a source's next page only when the merge has used up what it holds and needs its next item, so each source keeps the order the server gave it. Fetched pages are kept while the window is open (going back sends no request) until a toast asks for a tab (above); a page answered while the user already moved to another tab or page is dropped. Paging is by offset, so when a source shrinks while the window is open (an item handled in another browser tab or by a colleague), rows that move up into a page already fetched are not shown until the window opens again, and a later page can come back empty: it then answers with the last page that has items, with "Next" disabled. Only the first page shows the empty state, so "Nothing is waiting on you" is never said while items remain. A source that fails is named in a notice above the other sources' items, with "Try again"; a tab whose only source fails shows the error state. A new summary updates the counters; the shown page reloads only when the tab's set of sources changed, so rows do not move under the pointer.
- Table columns: item, type (and, in "All", the source), from, date as relative age (`frappe.datetime.prettyDate`, full date in the tooltip), priority and due date, status, "Open". Urgent and immediate are pills with an icon and a word, overdue rows add an "Overdue" pill and a 3 px inline-start stripe, normal is muted text [FR-UI-02 AC2]. Every value is set as text.
- Seen [FR-API-03]: once a tab's items are shown (or its empty state), each of its sources not yet marked during this opening of the window (or since a toast last asked for a tab) is marked seen with `mark_seen`, then the summary is fetched again so the "new" dots clear. "All" marks every action source; a source that failed to load is not marked.
- Keyboard and focus [FR-UI-08]: `Alt+Shift+A` toggles the window, registered through `frappe.ui.keys.add_shortcut` (with `ignore_inputs`) when available (Frappe matches shortcuts by key code, `frappe.ui.keys.get_key`). The window has `role="dialog"` and the title as its label, and `aria-modal` in dialog mode. Opening focuses the selected tab. In dialog mode Tab and Shift+Tab wrap around inside the window. The window element itself takes focus (`tabindex="-1"`) when a click lands on plain content or a focused control disappears or is disabled, so focus never falls back to the page; beside a panel or drawer, focus the user moved onto the page stays there when the window's content changes. `Esc` closes and stops the event, because Frappe's own Escape handler would otherwise also close a form dialog or grid row behind the window; a click on the backdrop closes too. The arrow keys, Home, End, Page Up and Page Down stop in the window as well, in every mode and on any of its elements (`util/keys.js`, `keepsKey`): Frappe's list view handles Up and Down on `window` (`frappe.ui.keys`) and checks for a focused input through `document.activeElement`, which is the window's host, so it would focus the first list row behind the window and cancel the key, and a radio group, the tone select, the volume slider or the scroll of the content would not move. Every other key reaches the desk, so `Alt+Shift+A` and the desk's own shortcuts still work while focus is in the window. Closing returns focus to the element that had it before opening, except after "Open" or "View all", when the new page owns focus, and except when the user had moved focus onto the page beside a panel or drawer. Tabs follow the WAI-ARIA tabs pattern with a roving tabindex and manual activation: the arrow keys (mirrored in RTL), Home and End move focus, Enter, Space or a click selects, because selecting fetches from the server.
- Live region (`role="status"`, `aria-live="polite"`) in the shadow root, created by the launcher bundle: the window announces each page ("Page 1. Items shown: 10"), the empty state and errors; the alerts will announce through it too. `prefers-reduced-motion` disables the pulse and slide animations.
- Translations: generic words of the client (`Open`, `Status`, `Item`, …) are wrapped with the context `"Attention Center"` (`__("Open", null, "Attention Center")`, third column of `ar.csv`); app-specific sentences carry none. Frappe merges the apps' translations into one dictionary in which a later app wins (`frappe.translate.get_translations_from_apps`), so a plain entry would replace another app's wording of the same word across the desk.
- Launcher: a pill button (bell, label, count) with a small collapse toggle on its inline-start side; collapsed, it is a 44 px circle with the count as a badge. Its accessible name states the count and the unseen info. Collapsing applies at once and is stored through `set_preferences`; preference writes are sent one after the other, so the stored value is the last click.
- Title counter: prefix `document.title` with the launcher's count text, `(N) ` or `(99+) `, and keep it in place across route changes: Frappe rewrites the title on navigation, and a `MutationObserver` on `<title>` re-applies the prefix after every rewrite. Only the prefix the app wrote is removed, so a page title that starts with a number in brackets stays intact.

### 7.3 Refresh loop [FR-RT-02]

- `realtime.js` (`startRefreshLoop`) triggers `store.refreshSummary(actor)` on:
  `frappe.realtime.on("attention_center_nudge")` (after a random 0–5 s wait when `broadcast`),
  `visibilitychange` → visible, the socket's `connect`, `window` `online`, and a heartbeat every
  `heartbeat_seconds` while the document is visible. socket.io 4 (4.8 in Frappe 15) emits `connect` on
  the socket after every reconnection too; its `reconnect` event belongs to the socket's manager, which
  `frappe.realtime.on` does not reach.
- Debounce: a burst of triggers is sent as one request once 1.5 s pass without another, or 5 s after its
  first trigger, so a steady stream of nudges still refreshes. A broadcast received while an earlier
  one's random wait is pending starts no second wait: the refresh after that wait covers it.
- A hidden tab sends no heartbeat but still follows nudges, so that its alerts can play (§7.5); becoming
  visible refreshes and starts the heartbeat again. The first fetch is the loop's first trigger, 1.5 s
  after `app_ready`: the boot never waits on it, and a socket that connects meanwhile joins it.
- `store.refreshSummary(actor)` sends one request at a time. A call while one is on its way sends no
  second request but asks for one more after it, shared by every call made meanwhile, because the
  change that prompted it may have been committed after the server read the counts. Its promise
  settles once that summary is stored or its request failed; a failed request does not reject it.
  The window's own refreshes (after `mark_seen`, "Try again") go through it too.
- The alert layer reads each stored summary through `store.onSummary(({previous, summary, actor}) =>
  …)`, `previous` being null for the first one of the page load. `actor` is the user named by the
  nudges a request answers when they all name the same one, and null otherwise: the heartbeat,
  visibility, reconnection, `online`, broadcasts and the window's refreshes name none, so
  self-suppression (§7.4) applies only when the user's own change is the only known cause. A request
  the loop sends while a broadcast waits out its random delay names none either: it already carries
  that broadcast's change. One limit remains, because the loop does not know when a request is sent
  or answered: a colleague's change whose nudge arrives while a request naming the user is on its way,
  or queued behind another, can reach the alert layer with the user as `actor`. The window lasts about
  one request, not the up to 5 s of a broadcast's wait.

### 7.4 Alerts [FR-ALERT-01..06]

- `alerts/policy.js` (`newItemAlerts`) is a pure function comparing the previous and next summary, one alert per source that gained items: a source whose `count` grew brought that many new items; one whose `latest` grew while its count did not brought one (an item arrived as another was handled, or the count sits at its cap). Only sources in state `ok` in both summaries are compared, so a source that appears or recovers from an error raises nothing. The level is `info` for an info source; for an action source `immediate` when its `immediate` count grew, else `urgent` when its `urgent` count grew, else `normal` (overdue is no level: an item turning overdue changes neither count nor latest). It applies the scope table of FR-ALERT-02 (the sound is named by its role, `standard`, `urgent` or `immediate`, which the sound engine maps to a tone), self-suppression (`actor === session user` on the triggering nudge), and Do Not Disturb (`dnd_until` later than `frappe.datetime.system_datetime()`, both naive system-time text: no sound, the toasts stay). `reminderAlert` is the table's reminder row: a toast and the `reminder` tone at every scope, silent during Do Not Disturb. The very first summary after page load produces no "new item" alerts (it feeds the login logic instead).
- `alerts/coalesce.js` merges the alerts of a burst, every alert within `coalesce_seconds` of its first, into one toast and one sound. The first alert is shown and heard at once, so an immediate item never waits for the window to end; later ones update the same toast ("N new items", the highest level so far, sticky once an immediate item is in it) and sound only when more pressing than the sound the burst already played. A burst of equal or lower alerts therefore sounds once, and its last sound is always that of its highest level. Alerts that neither toast nor sound (new info outside the "everything" scope) start no burst.
- Toasts (`ui/toast.js`) [FR-UI-07]: at most three cards stacked above the launcher, newest nearest, never focused. Each has an icon, the level as a worded pill for urgent and immediate, one line of text ("New item in {source}", "{n} new items in {source}", or "{n} new items" when several sources contributed), "View" and a close button, and is spoken through the live region. A click opens the window on the tab of the burst's only source, or on "All"; the toasts lie over the open window in every mode (§7.1), so a click while it is open shows that tab with its items fetched afresh (§7.2), and a press leaves focus where it was (in the modal dialog, or in the page's field). Normal and urgent toasts leave after 8 s; immediate ones stay until closed or clicked; a fourth toast replaces the oldest one that is not sticky, and when all three are sticky only another immediate toast replaces the oldest, while a less pressing one is not shown. The launcher pulses once on every new-item alert (none for the user's own changes).
- Login (`alerts/login.js`, `autoOpenOnLogin`): on the first summary of the page load, if `boot.should_auto_open` and effective `auto_open_on_login` and `totals.action > 0`, open the window on "All" and, once it is open, call `note_auto_opened()` and restart the reminder interval (below). No later summary opens it, even when the first held no action items: those bring their own toast, and a window opening while the user types takes their keystrokes (D-03). A page load that opens nothing (no action items, auto-open off, a window bundle that did not load) records nothing, so the next page load of the login session decides again; a window the user opened before the first summary is left on its tab and recorded. The summary line is the sum of `new_since` over action sources, taken from the summary held before the window opens: the window opens on "All", which marks every action source seen at once and fetches the summary again (§7.2), after which `new_since` reads 0. The launcher hands the count to the window in `store.ui.newSince` (null for any other opening); the window shows it as a strip under the header ("3 new items since you last looked", "Nothing new since you last looked" for none) that also describes the dialog (`aria-describedby`).
- Reminder (`alerts/reminder.js`, `startReminder`): a one-minute timer in every tab checks `totals.attention > 0` and `now - lastReminderAt ≥ interval` (`reminder_interval_hours`, 0 turns it off); `lastReminderAt` lives in `localStorage` (`attention_center:last_reminder`, epoch milliseconds) so all tabs share it, and the tab that reminds writes it first. The interval starts, without a reminder, at a check that finds attention items after one that found none, in a browser with no stored time, and when the window opened by itself at login: otherwise the first urgent item after a quiet spell, or the login window, would be followed by a reminder within a minute. A hidden tab reminds only 2 minutes after the reminder is due, so that a visible tab, which checks every minute, reminds whenever there is one; with no visible tab a hidden one still reminds, its tone reaching a user who works in another window. The reminder is `reminderAlert`: a toast that is not sticky, "Reminder: urgent or overdue items are still waiting for you" (no number: `totals.attention` may count an item twice, §5), whose "View" opens the window on "All" (nothing else does), and the `reminder` tone through `sound.alert` under the id `reminder@<previous lastReminderAt>`, so that two tabs that remind in the same moment claim one sound. A tab whose storage refuses the write keeps its own time and reminds once per interval on its own. Limits: a hidden tab whose socket gave up holds an old summary, so it may remind of items handled meanwhile, or restart the interval when it becomes visible; a reminder shown by a hidden tab leaves after 8 s like any toast, its tone being what the user notices.

### 7.5 Sound [FR-SND-01..04]

- `public/sounds/tones.json` lists tones: `{id, file, role: "standard" | "urgent" | "immediate" | "reminder", label}`. Files are produced by `scripts/sounds/generate_tones.py`; never hand-edit or replace them with third-party audio. The boot sends them as `tones: [{id, role, label, url}]` (§5); the four tone selects of the settings list the same ids (§3.1).
- `alerts/sound.js` (`createSound`) plays the tone of a role: `standard` is the user's `tone`; `urgent`, `immediate` and `reminder` are the settings' `urgent_tone`, `immediate_tone` and `reminder_tone`. One `HTMLAudioElement` per tone, created on its first play (`new Audio(url)`), with `volume = pref.volume / 100`; volume 0 plays nothing and claims nothing.
- Mute sources, in order: `frappe.boot.user.mute_sounds`, DND active, scope rules. The engine checks the first two before every sound, whatever its role, so the urgent, immediate and reminder tones, which play at every scope, are silenced too [FR-SND-02 AC1]. The alert policy applies DND and the scope as well (§7.4), so a burst never counts a silenced sound as played.
- Locked audio [FR-SND-03]: a `play()` rejected with `NotAllowedError` locks the tab. The launcher pulses; the first time in the page load a hint toast explains it (no "View", no timer, so a user who was away still finds it); capture-phase `pointerup` and `keydown` listeners on `window` unlock the tab at the next gesture by playing a muted tone, after which the hint goes and sounds play again without a reload. `pointerup` rather than `pointerdown`: a touch grants the permission only when it ends. A locked tab claims no alert (below), so another tab can play it. A gesture the browser does not count (Escape) unlocks nothing: a browser that refuses the muted tone too until a counted gesture (Chromium) keeps the tab locked and waits for the next gesture; one that plays muted tones at any time unlocks the tab, refuses the next sound and so locks it again, without a second hint. A hint the toast stack has no room for (three immediate toasts) is not tried again: those toasts leave only by a click or a key, which unlocks the sound. Other refusals (a file that does not load) are ignored.
- Cross-tab single playback (`alerts/tabs.js`) [FR-SND-04]: a sound gets an id from the summary that raised it (`alertId`): the key, `count` and `latest` of each source whose alert sounds. Tabs fetch the same summary for a change, so they compute the same id even when they fetch it seconds apart (a broadcast's random wait, §6), where a bucket of the clock would split them at its edge. Claims go by a key, the FNV-1a hash of the id, so that `localStorage`, which outlives the session and may be read by the next user of the browser, names no source and no count. A tab that finds the key claimed (a live `attention_center:claim:<key>` in `localStorage`, or a `{claim: key}` message heard on `BroadcastChannel("attention_center")`, which can arrive before the write does) leaves it. Otherwise it claims it: at once when visible, after 120 ms + random 0–80 ms when hidden (checking again first), so that visible tabs win. A tab that has not shown that the browser lets it play, with no gesture the browser counts since the page loaded (`navigator.userActivation.hasBeenActive`) and no sound played, waits 2.5 s more, so that a tab that has, even a hidden one, claims first: a tab opened in the background or reloaded, and not clicked yet, would otherwise win and be refused, and the alert would play in no tab. The browser runs a hidden tab's timers up to about a second late, both the refresh that fetches the change there and the claim's delay, hence 2.5 s. Among the tabs of each kind visible ones still win. Claiming writes `attention_center:claim:<key>` = `{tab, at}` with the tab's random id and posts `{claim: key}`; 120 ms later the tab plays only if the stored claim is its own, so of two tabs that wrote at the same moment the later write stands in both and one plays. A tab whose sound the browser then refuses gives the claim back: it removes its stored claim and posts `{release: key}`, so that a tab that fetches the change later plays it. When `localStorage` refuses the write (full, or disabled) the tab plays anyway: the posted claim still keeps the tabs that check after it silent, and a sound in two tabs is better than in none, or than a storage error stopping the client. Claims older than 30 s are ignored and removed at the next write. No Web Locks, no service worker, no Notification API, no `crypto.randomUUID`: the production origin is plain HTTP [NFR-COMP-02].
- `sound.preview(id)` plays a tone once for the settings view (§7.6): in the tab that asks, without a claim, at the user's volume, and not at all under `mute_sounds`, Do Not Disturb or volume 0. It follows a click, so a refusal is ignored and locks nothing.
- The client hands every summary's alerts to the engine in one call, `sound.alert(role, id)`, `role` being the tone role coalescing returned (§7.4) or null when the tab's burst already sounded. With a null role nothing plays, and the id is marked as claimed, so that a tab that fetches the same change later (after a longer broadcast wait, in one summary) stays silent, but only when the tab's burst was heard: played in this tab or claimed by another. A tab whose burst was silent (`mute_sounds`, Do Not Disturb, volume 0, locked, or refused by the browser) marks nothing, even when a gesture unlocked it since, so another tab plays the burst.
- Limits: tabs whose summaries split a burst differently compute different ids and may each play once. A tab that has not shown it can play still claims when no tab that has claims within its 2.5 s (it fetched the change sooner, after a broadcast's random wait); refused, it gives the claim back, and the sound is lost only for a tab that checked in the moment before (the hint shows in the refused tab). Alone, such a tab shows the hint, or plays its first sound when the browser allows it, 2.5 s after the toast. Claims live 30 s, so a tab that missed the nudges (its socket gave up, T-05) and refreshes minutes later, when it becomes visible, plays again for items another tab sounded; a longer life would instead silence an item that leaves the user's queue and comes back with the same count and latest date (sent back and resubmitted), which is the worse failure. Within those 30 s, a source whose count and latest date return to the same values gets the same id, and its second alert is silent.

### 7.6 Settings UI [FR-SND-02, FR-SET-02, FR-UI-03]

A settings view inside the window (`ui/settings.js`, window bundle) edits the user's preferences
through `set_preferences`. A settings button in the window's header (`aria-pressed`, before the
mode button) shows it in place of the tabs and their panel, and shows the items again when pressed
again; "Back to the list" does the same and focuses the selected tab. The window opens on the
items every time, and a toast's "View" shows the items too. Items answered while the settings
show are not marked seen; going back draws the page again from the pages already fetched, which
marks them.

- Controls: sound scope (three radio buttons), standard tone (a select of the boot's `standard`
  tones) with "Preview", volume (a range 0–100, applied and stored when the user lets go), Do Not
  Disturb (off / for 1 hour / until the end of the day), auto-open after login (a checkbox) and
  display mode (three radio buttons). There is no control for the launcher's counter or for the marks
  of urgent, immediate and overdue items: no preference exists for them (D-06); the view says so in
  one line. Each control shows the effective preference from the store and redraws when the store's
  preferences change, from another tab included. The view writes explicit values: the effective
  preferences do not say which values are inherited, so it offers no "use the default" choice, and a
  preference the user never changes keeps following the settings' default.
- Changes (`util/settings.js`, `createPreferenceEditor`): a change replaces the store's
  preferences at once, so the sound engine, the alert policy and the window follow it, and is sent
  through `api.setPreferences` (one write after the other). Only values that differ are sent;
  auto-open is sent as `Yes`/`No`. The view shows "Saving…", "Saved", or "Your change could not
  be saved." with "Try again", which sends the preferences whose last write failed with their current
  values. A failed change keeps applying in the page load. The header's mode button goes through the
  same editor.
- Do Not Disturb (`util/time.js`): chosen in the user's time zone (`frappe.datetime.now_datetime`),
  "for 1 hour" ends an hour later and "until the end of the day" at the user's next midnight; the end
  is converted to the system time zone (`convert_to_system_tz`) before it is stored and compared,
  like every time of §7.4. The shown choice is derived from `dnd_until`: off once it has passed,
  "until the end of the day" when it ends at the user's next midnight, else "for 1 hour" with its end
  time ("Sounds are off until 15:30. Alerts still show."). The view redraws when it ends.
- Preview: `sound.preview(id)` (§7.5) plays the selected tone once at the user's volume in this tab,
  without a claim. `mute_sounds`, Do Not Disturb and volume 0 keep it silent like every sound
  [FR-SND-02 AC1], so the button is disabled then, and a note says when `mute_sounds` is set.
- Other tabs (`util/share_prefs.js`): every change of the store's preferences that did not come from
  the channel is posted on `BroadcastChannel("attention_center")` as `{changes, user}`, `changes`
  holding only the preferences whose value changed; the user's other tabs apply them over their own,
  so Do Not Disturb set in one tab silences an alert another tab would play, and a tab holding older
  values for the other preferences (changed in another browser, or a write that failed there) does
  not overwrite them. A tab of another user ignores it. The launcher's collapse travels the same way.

### 7.7 Admin desk [FR-SRC-02 AC2, FR-SET-01, FR-SET-03]

Managers configure the app in the standard desk forms of the two DocTypes, which only System Manager and
Attention Manager may open (their DocType permissions), with a form script each (`<doctype>.js` beside the
DocType JSON; plain desk scripts, not modules of the client bundles).

- Workspace `Attention Center` (module `Attention Center`, `roles`: Attention Manager, System Manager, so the
  sidebar lists it for them only; `sequence_id` 30, after the core workspaces): shortcuts to the settings and to
  the list of sources.
- `Attention Center Settings`: the controller's `onload` sends `__onload.tones` (`[{value: id, label}]`, the
  translated labels of `preferences.get_tones()`), and the form script sets them as the options of the four tone
  selects, so the admin picks "Chime" rather than `chime`. The DocType's own options stay the ids of
  `tones.json` (a test keeps them equal), because Frappe validates a Select against them on save. An intro says
  that users get changed settings at their next page load: the client reads them from the boot.
- `Attention Source`: the section of the other type is hidden by `depends_on` (in the DocType). `source_type` is
  read-only, since a source made in the desk can only be a DocType Query [FR-SRC-03 AC2]; `is_system` and `app`
  show for system sources only. On a system source every definition field (all but `ADMIN_FIELDS`) is read-only
  and an intro names the declaring app [FR-SRC-01 AC2]; the server enforces both anyway (§3.2). "Test for my
  user" shows on a saved source for users with a manager role; it refuses a form with unsaved changes, because
  `test_source` runs the stored definition, then shows the counts, the first five items (title as a link to the
  item in a new browser tab, sender, age, priority and overdue pills) and the duration, or a failure line when the
  run's state is `error`. Every value from the source is escaped (`frappe.utils.escape_html`). The dialog says
  that the test uses the manager's own permissions, so others may see other items.
- `hide_standard_bell` (D-14): the launcher bundle, when it is evaluated and before the desk draws its navbar,
  adds one `<style>` to the page's head with `.navbar .dropdown-notifications { display: none !important; }`
  (`util/bell.js`), the selector of the bell in Frappe 15's `navbar.html`. It is the only style the app puts
  outside its shadow root. A navbar that differs (a theme, Frappe 16) does not match and keeps its bell. The
  rule is registered as a cleanup of the guard, so a failure of the client shows the bell again along with
  removing the launcher.

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
holds simple, familiar Arabic. `tests/test_translations.py` extracts every `_()`/`__()` literal of
the app's Python and JavaScript with the extractors of `bench generate-pot-file`, adds the texts
the app translates from its data (tone labels, labels of the built-in sources), and fails when one
lacks a row in `ar.csv` with Arabic text and the same placeholders, or when a row without context
would change Frappe's own Arabic for the text [NFR-I18N-01]. The extractors lose a text's context
when a call sits among the arguments of `__()`, and take any literal inside `_()` for a text: keep
the other arguments plain values. Dates and "x ago" text use Frappe's client utilities so they
follow the user's locale.

## 10. Test strategy [NFR-MAINT-01]

- **Backend** (`bench --site <site> run-tests --app attention_center`): `FrappeTestCase` from `frappe.tests.utils` (Frappe 15). Each test creates its own users/roles/documents and cleans up via rollback. Mandatory coverage: source-definition validation; declarative executor (placeholders, mapping, caps, ordering); permission filtering with role permissions, a User Permission, and a `permission_query_conditions` fixture DocType created in the test; approvals with "role but no read permission"; targeting narrowing; fault isolation (a raising python source); cache TTL and invalidation; recipients and single nudge per request (`frappe.publish_realtime` patched); API input validation and "cannot read another user's data"; preferences validation; translation completeness.
- **Client pure logic**: `node --test tests/js/*.test.js` (Node 22 no longer takes a directory argument) for policy, coalescing, tab coordination (fake channel/storage/clock), reminder scheduling, escaping and route validation. No browser needed.
- **UI smoke** (M6-T1): `tests/ui/test_smoke.py`, Python Playwright run by `scripts/ci/run_tests.sh` with the system `python3`, and skipped with the reason when Playwright or its Chromium is missing, as in CI. It completes the setup wizard if needed, serves the site with `bench serve`, creates a desk user with an assignment and a notification, and checks the launcher and the window in English (LTR) and Arabic (RTL), light and dark: the inline-end corner, translated texts, the theme's surface, `Esc` and the shortcut, and the three display modes right to left. `AC_UI_SCREENSHOTS=<dir>` keeps a screenshot of each window. Kept small.
- **Contrast**: `tests/js/contrast.test.js` reads the tokens of `ui/styles.js` and checks every text colour on the background the stylesheets put it on, in both themes, against WCAG 2.1 AA (4.5:1) [NFR-A11Y-01].
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
