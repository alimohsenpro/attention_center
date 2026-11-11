# Provider guide: adding a source to Attention Center

This guide is for the developer of a Frappe app (the *consumer app*) who wants the app's "waiting on
you" lists to appear in Attention Center. It is the whole contract: you should not need to read
Attention Center's code. Budget: half a working day for a first source, tests included.

A runnable example lives in [`examples/sample_app/`](../examples/sample_app/): one declarative and
one python source over a `Sample Request` DocType. `attention_center/tests/test_examples.py` runs it
on a site as if it were installed, so everything it shows works.

Contract version: **1** (`contract_version: 1`).

## 1. Quick start

1. Choose a key: `<your_app>.<identifier>`, lowercase letters, digits and underscores
   (`sample_app.my_requests`). The key identifies the source for good: admins' settings hang on it.
2. Add an `attention_sources` list to your app's `hooks.py`. It is plain data; do not import
   anything from `attention_center`:

   ```python
   attention_sources = [
   	{
   		"key": "sample_app.my_requests",
   		"contract_version": 1,
   		"label": "My Requests",
   		"kind": "action",
   		"type": "doctype_query",
   		"doctype": "Sample Request",
   		"filters": [["status", "=", "Open"], ["assigned_to", "=", "{user}"]],
   		"fields": {"title": "subject", "from": "owner", "date": "creation",
   		           "priority": "priority", "due": "due_date", "status": "status"},
   		"priority_map": {"High": "urgent", "Critical": "immediate"},
   		"recipient_fields": ["assigned_to"],
   		"list_route": "/app/sample-request?status=Open",
   	},
   ]
   ```

3. Run `bench --site <site> migrate`. Attention Center reads the hooks of every installed app at each
   migrate (and when it is itself installed), so run it also after installing your app.
4. As a System Manager or Attention Manager, open **Attention Source** (`/app/attention-source`),
   open your source and press **Test for my user**: it shows your count, your first five items and how
   long the source took.
5. Reload the desk: the launcher in the bottom corner counts your items, and the window has a tab
   named after your label.

If the source does not appear, see [Troubleshooting](#11-troubleshooting).

## 2. Declarative or python?

| Use | When |
|---|---|
| `doctype_query` (declarative) | The items are the rows of one DocType that a fixed list of filters selects, possibly with `{user}` and `{today}` in the values. Most "assigned to me" and "waiting for my role" lists. No code; an admin could also build it in the desk |
| `python` | Anything else: the user's teams or units, conditions joined by OR, rows from several DocTypes, a per-document permission check, computed priorities. You write two functions (three with recipients) |

Both run as the logged-in user when the user's browser asks (counts are kept for a minute); nothing
is copied or stored.

## 3. The hook entry

Every entry is a dict in the `attention_sources` list of your `hooks.py`.

### Keys of every entry

| Key | Required | Value |
|---|---|---|
| `key` | yes | `app.identifier`: matches `^[a-z0-9_]+(\.[a-z0-9_]+)+$`. Unique on the site |
| `contract_version` | yes | the integer `1` |
| `label` | yes | the tab's name, in English; see [Translations](#9-translations) |
| `kind` | yes | `"action"`: work waiting on the user. It counts in the launcher's badge and the browser tab's title, raises toasts and sounds, and urgent, immediate and overdue items bring periodic reminders. `"info"`: something to know. It shows an unseen dot, no toast, and a sound only for users who chose "everything" |
| `type` | yes | `"doctype_query"` or `"python"` |
| `list_route` | no | a desk route starting with `/app/`, opened by the window's "View all" (`/app/sample-request?status=Open`) |
| `icon` | no | text; stored and returned by the API, not drawn by the 0.1 window |

The order of the tabs and who sees a source are the admin's (section 8): an entry has no key for them.

### How entries are checked

At each migrate every entry is checked. A rejected entry is skipped and logged at ERROR in
`attention_center.log` (section 10) with your app's name and the entry's position, and the other
entries still load. An entry is rejected when:

- `contract_version` is not a supported integer, the key does not match the pattern, or a required key is missing or of the wrong type;
- it holds a key that its `type` does not define (a misspelt `filter` is rejected, not ignored, because ignoring it would widen the query);
- `filters` or `priority_map` hold a value JSON cannot store (a `date`, a `set`): write dates as `"2026-01-31"` or use `{today}`;
- a declarative entry names a DocType or field that does not exist, an operator that is not allowed, or an unknown placeholder;
- another installed app already declared the key (the app installed first keeps it), or an admin created a source with that key in the desk (the desk source is left alone).

## 4. Declarative sources (`"type": "doctype_query"`)

| Key | Required | Value |
|---|---|---|
| `doctype` | yes | a DocType with its own records (not a child table, not a Single) |
| `fields` | yes | maps roles to fieldnames: `title` and `date` required; `from`, `priority`, `due`, `status` optional |
| `filters` | no | list of `[fieldname, operator, value]`, all of which must hold (AND) |
| `priority_map` | no | `{"<value of the priority field>": "urgent" \| "immediate" \| "normal"}`; needs `fields.priority` |
| `recipient_fields` | no | fieldnames holding a user id: the users to nudge when a row changes (section 7) |
| `route_fields` | no | `{"route": f, "doctype": f, "name": f}`: what an item opens instead of the row itself |

Fieldnames may be your DocType's fields or the standard columns `name`, `owner`, `creation`,
`modified`, `modified_by`, `docstatus` and `idx`.

**Filters.** Operators: `=`, `!=`, `>`, `<`, `>=`, `<=`, `in`, `not in`, `like`, `is`.
`in` and `not in` take a list (`["status", "in", ["Open", "Pending"]]`), `is` takes `"set"` or
`"not set"`, the others one text or number. Two placeholders are replaced inside values, never
elsewhere: `{user}` (the user's id) and `{today}` (the site's date, `YYYY-MM-DD`), as in
`["assigned_to", "=", "{user}"]` or `["due_date", "<=", "{today}"]`. Values reach the query as
parameters, never as SQL text. Conditions joined by OR need a python source.

**Field roles.**

| Role | Becomes | Notes |
|---|---|---|
| `title` | the item's text | HTML is stripped; cut at 200 characters |
| `date` | the item's date and age | the list is newest first by this field; it decides what is "new since the user last looked" (a date-only field counts from midnight) |
| `from` | the "From" column | a user id shows as the user's full name; any other value as it is |
| `priority` | the priority | through `priority_map`; without a map the field must hold `urgent`, `immediate` or `normal` itself. Anything else is `normal` |
| `due` | the due date | the item is overdue once it passes: a date from the next day on, a datetime at once |
| `status` | a status badge | the value, translated with `_()` |

**Route.** An item opens the value of `route_fields.route` when that field holds a desk route
(`/app/...`), else the document named by the `doctype` and `name` fields when the row sets both
(give both or neither), else the row's own form. Frappe's ToDo, for example, opens the document it is
about: `"route_fields": {"doctype": "reference_type", "name": "reference_name"}`.

**What runs.** For each user, `frappe.get_list` as that user: their role permissions, User
Permissions and your DocType's `permission_query_conditions` all apply, and fields above their
permission level come back empty. A user who may not read the DocType does not get the tab at all.
The count reads the newest 100 rows (shown as "99+" beyond 99); the items are those rows ordered
overdue first, then immediate, urgent, normal, newest first within each; past 100 pending rows the
rest follows in date order.

## 5. Python sources (`"type": "python"`)

| Key | Required | Value |
|---|---|---|
| `get_count` | yes | dotted path of your count function |
| `get_items` | yes | dotted path of your items function |
| `get_recipients` | no | dotted path of a function naming the users to nudge when a watched document changes (section 7) |
| `watch_doctypes` | no | DocTypes whose changes may move your counts (section 7) |

A dotted path starts with your app's package (`sample_app.attention.team_queue_count`): Frappe
refuses a path whose first part is not an installed app. Python sources can only come from hooks;
admins cannot create one in the desk.

### The functions

```python
def get_count(user: str, since: datetime | None = None) -> int | dict:
	"""How many items wait on `user`; see "Counts" below for the dict.

	`since`, optional in your signature, is when the user last looked at this source (a naive datetime in
	the system time zone), or None if they never did. Attention Center passes it only if you accept it.
	"""


def get_items(user: str, start: int, page_length: int) -> list[dict]:
	"""Items start .. start + page_length of your list, in the order to show them; see section 6.

	Attention Center asks for one item more than a page to know whether another page follows.
	"""


def get_recipients(doc: Document) -> list[str]:
	"""The users whose lists the change of `doc` (a document of a watched DocType) may have changed."""
```

**Counts.** Return an integer, or a dict:

| Key | Required | Value |
|---|---|---|
| `count` | yes | items waiting; whole number ≥ 0 |
| `urgent`, `immediate`, `overdue` | no | how many of them are urgent, immediate, overdue |
| `latest` | no | date of the newest item: `datetime`, `date` or ISO text |
| `new_since` | no | items newer than `since` (all of them when `since` is None) |

Every number is capped at 99. Return the dict when you can, because the browser decides what to
signal from it: an alert fires when `count` grows or `latest` moves on (an int alone misses an item
that arrives as another is handled), its level comes from the growth of `immediate` and `urgent`
(without them every new item sounds like a normal one), `urgent + immediate + overdue` drives the
periodic reminder, and `new_since` drives the info dot and the "new since you last looked" line at
login. Anything else (text, a negative number, `True`, a bad `latest`) fails the source.

**Rules your functions must follow.**

1. **Run as the user.** Attention Center calls them in the user's own request, with
   `frappe.session.user == user`. Read with `frappe.get_list(..., user=user)` and check documents with
   `frappe.has_permission(doctype, "read", doc, user=user)`. Do not use `frappe.get_all`,
   `frappe.db.sql` or `ignore_permissions` for the rows you return: the user must never see an item
   they could not open.
2. **Return nothing rather than fail.** A python source is shown to every desk user unless an admin
   targets it, and Attention Center does not check its DocTypes. Return `0` and `[]` to a user who
   may not read them: an exception shows the tab as failed for that user.
3. **Stay fast.** Read at most 100 rows and use one or two queries. Every database statement your
   source runs is stopped after 2 seconds, which fails the source; a call slower than 2 seconds in all
   is logged as slow. Counts are cached per user for `summary_cache_ttl` (60 s by default), items are
   not.
4. **Fail quietly.** An exception marks only your source as failed (`state: "error"`) for that user;
   the other sources load. The log gets your key, the user, the duration and the exception's type,
   never its message, because a message may quote a document. Messages you queue with
   `frappe.msgprint` or `frappe.throw` are dropped, so they never open a dialog over the user's work.
5. **Log no content.** If you log, log keys, user ids, counts and durations, never titles or fields.

The example's [`attention.py`](../examples/sample_app/attention.py) follows all five.

## 6. Items

What `get_items` returns, one dict per item. A declarative source builds the same dicts from the
field roles.

| Key | Required | Value |
|---|---|---|
| `id` | yes | text or integer, unique within your source |
| `title` | yes | plain text; HTML is stripped, whitespace collapsed, cut at 200 characters |
| `route` | yes\* | desk route starting with `/app/` |
| `reference_doctype`, `reference_name` | yes\* | the document to open, instead of `route` |
| `type_label` | no | short label shown as the item's type |
| `from_label` | no | the "From" column as text; or `from_user`, a user id shown as the user's full name |
| `date` | no | when the item arrived: `datetime`, `date` or ISO text |
| `priority` | no | `"normal"` (default), `"urgent"` or `"immediate"` |
| `due` | no | due date or datetime; Attention Center computes `overdue` from it |
| `status_label` | no | short text shown as a badge |
| `status_color` | no | `gray` (default), `blue`, `green`, `orange` or `red` |

\* One of the two.

- An item without a valid `id`, `title` or route, or repeating an earlier `id`, is dropped; a warning with your key and the number dropped goes to the log.
- An invalid optional value (an unknown priority, a malformed date) falls back to its default instead of dropping the item: the user can still open it.
- Dates with a time zone are converted to the system time zone; text dates must be ISO (`2026-11-30`, `2026-11-30T09:15:00`).
- Keys not in the table are dropped. All text is shown as text, never as HTML.

```python
{
	"id": "SR-0042",
	"title": "Server room is too warm",
	"reference_doctype": "Sample Request",
	"reference_name": "SR-0042",
	"type_label": "Facilities",
	"from_user": "requester@example.com",
	"date": datetime(2026, 11, 11, 9, 15),
	"priority": "immediate",
	"due": date(2026, 11, 12),
	"status_label": _("Unassigned"),
	"status_color": "orange",
}
```

**What priorities do.** A new normal item raises a toast and the user's own tone. A new urgent item
plays the organisation's urgent tone whatever sounds the user chose, an immediate one also keeps its
toast until it is closed, and while urgent, immediate or overdue items wait a reminder repeats (every
2 hours by default). Only Do Not Disturb or muting every sound silences them, and their visual marks
cannot be turned off, so keep `urgent` and `immediate` for work that really cannot wait.

## 7. Keeping counts fresh

When a document changes, Attention Center tells the browsers of the users concerned to refresh (a
*nudge*: it names the source, never the document). Without nudges a user's count catches up within
`summary_cache_ttl` (60 s by default) of their browser's next refresh: it refreshes when the tab
becomes visible, when the socket reconnects, and every 5 minutes (by default) while visible.

**Which changes.** Insert, save, submit, cancel, `doc.db_set` and delete of a document of a watched
DocType. A declarative source watches its `doctype`; a python source watches its
`watch_doctypes`. Frappe raises these events for the parent document only: list parent DocTypes, and
a child row edited through its parent arrives with the parent's save. Changes made during install,
migrate or a data import send no nudge.

**Which users.**

- Declarative: the users in `recipient_fields`, before and after the change, so a reassignment nudges both people.
- Python: what `get_recipients(doc)` returns. It runs in the request of whoever made the change, as that user, so it must not depend on `frappe.session.user`; `doc.get_doc_before_save()` gives the previous version on a save (None on insert). Listing users only to nudge them may use `frappe.get_all`: nobody is shown the list.
- No `recipient_fields` or `get_recipients`, a `get_recipients` that raises or returns something other than a list (logged at ERROR), or more than 200 users: one nudge goes to every desk user, whose browsers refetch after a random delay of up to 5 s. That is correct but costs every user a request; give recipients when you can.

Nudges are sent once the transaction commits, at most one per user per transaction, and not at all
when it rolls back.

**Changes without a document event.** `frappe.db.set_value`, `frappe.db.sql` and bulk updates raise
no event. After one, nudge the users yourself, only when Attention Center is installed:

```python
def nudge_attention_center(users: list[str], source_key: str) -> None:
	if "attention_center" in frappe.get_installed_apps():
		frappe.get_attr("attention_center.engine.realtime.nudge")(users, source_key)
```

`nudge(users, source_key)` raises `frappe.ValidationError` for a key that is not a source on the site
and for `users` that are not a list of user ids, sends after the commit like the others, and nudges
every desk user above 200 users. It accepts a disabled source.

## 8. What admins control

Hook sources are synced into **Attention Source** documents at every migrate, marked as system sources
of your app. An Attention Manager or System Manager can:

- enable or disable the source, change its sort order and relabel it;
- target it to roles and user groups: no targeting means every desk user, otherwise a user needs one listed role or membership in one listed group. Targeting only narrows: a user never sees an item they cannot open.

Everything else is your definition and is read-only in the desk. At the next migrate after you change
your entry, the definition follows it; the label follows yours until an admin changes it, after which
the admin's label stays. An entry you remove, or one that becomes invalid, disables its source and
keeps it (with its last valid definition), and the source stays disabled when the entry comes back
until an admin enables it again. A new key is a new source: the old one is disabled, and its targeting
is not carried over.

Uninstalling your app: run `bench --site <site> migrate` afterwards to disable its sources. Until
then a python source whose app is gone shows as failed and a declarative one whose DocType is gone is
hidden.

## 9. Translations

`label` is English. Attention Center translates it with `_(label, context="Attention Source")`, which
falls back to a row without context, so ship the translations in your app's
`translations/<lang>.csv`:

```csv
"My Requests","طلباتي","Attention Source"
"Team Queue","طلبات الفريق","Attention Source"
```

A row with the context changes the label in Attention Center only; a row without one (`""`) also
applies wherever else the desk shows that text. A declarative source's status values are translated
with `_(value)`; a python source translates its own `type_label` and `status_label` with `_()`, since
it runs in the user's request and language.

## 10. Checking your source

- **Test for my user** in the source's form (section 1) runs it for you, enabled or not, and shows the counts, the first five items, the duration, or that it failed.
- As any desk user, open `/api/method/attention_center.api.get_summary` in the browser for that user's counts, and `/api/method/attention_center.api.get_items?source=<key>` for the first page.
- The log: `logs/attention_center.log` in the bench and `sites/<site>/logs/attention_center.log`. Production logs ERROR only; the warnings below appear with `bench start` (developer server).

| Log line | Level | Meaning |
|---|---|---|
| `<app>: attention_sources entry <n> skipped: <reason>` | ERROR | the entry breaks the contract (section 3) |
| `<app>: hook source <key> skipped: <reason>` | ERROR | the source form rejected it (unknown DocType or field, bad filter), or a desk source has the key |
| `system source <key> disabled: no installed app declares a valid entry for it` | WARNING | the entry was removed or became invalid |
| `source <key> failed for <user> after <ms> ms: <exception type>` | ERROR | the source raised, timed out, or returned a wrong shape (then the reason follows) |
| `source <key> was slow for <user>: <ms> ms` | WARNING | over 2 s in all |
| `source <key>: dropped <n> of <m> items ...` | WARNING | items without `id`, `title` or route, or with a repeated `id` |
| `source <key>: get_recipients failed for a <DocType> change: <exception type>` | ERROR | the change was broadcast instead |

**Automated tests.** Your functions need no Attention Center: test them directly as each user
(`frappe.set_user(user)`, then call them), with a second user who must not see the first user's
items. To test the whole path on a site where Attention Center is installed, sync your entries with
`bench migrate` (or `attention_center.engine.registry.sync_sources()` in a test) and call
`attention_center.api.get_summary()` and `get_items(key)` as the user. The example's tests do both.

## 11. Troubleshooting

| Symptom | Look at |
|---|---|
| The source is not in the Attention Source list | Did migrate run after the change? Is there an "entry skipped" or "hook source skipped" line in the log? Does a desk source use the key? |
| It is in the list but a user has no tab | Is it enabled (a removed entry disables it, and it stays disabled)? Does the targeting include the user? For a declarative source, may the user read the DocType? |
| The tab shows an error | The "failed for" line: an exception, a statement over 2 s, or a count or item list of the wrong shape |
| Items are missing | The "dropped" warning: each item needs `id`, `title` and a route (`/app/...`, or `reference_doctype` and `reference_name`), with distinct ids |
| A count lags behind | Is the changed DocType watched? Was it changed with `frappe.db.set_value` or SQL (call `nudge`)? Does the change's user list include the user? |
| "App ... is not installed" | A dotted path must start with your app's package name |

## 12. Not depending on Attention Center

Your app must work the same on a site without Attention Center:

- `attention_sources` is plain data in `hooks.py`; Frappe ignores hooks no installed app reads.
- Never import `attention_center`, at module level or inside a function; do not add it to `required_apps`. Your functions are called by dotted path.
- Call `nudge` only behind the installed-apps check of section 7.

`test_examples.py` checks that the example app imports nothing from `attention_center`.

## 13. Versioning

The contract is version 1. A change that would break version 1 entries or functions comes as version 2,
with version 1 still accepted. An entry with a version this release does not know is skipped and
logged, so state the version you wrote against.

## 14. Checklist

- [ ] The key is `<your_app>.<identifier>` and will not change.
- [ ] The label is English, with translations in your app's `translations/`.
- [ ] `kind` is `action` only for work waiting on the user; `urgent` and `immediate` are rare.
- [ ] Declarative: every condition is in `filters`; `recipient_fields` names the user fields.
- [ ] Python: `frappe.get_list(..., user=user)` and `frappe.has_permission` only; 0 and `[]` for users who may not read; at most 100 rows; the count dict with `latest`, `urgent`, `immediate` and `new_since`.
- [ ] Python: `watch_doctypes` lists the parent DocTypes that move the counts; `get_recipients` returns user ids.
- [ ] Changes made without document events call `nudge` behind the installed-apps check.
- [ ] No import of `attention_center`; no item content in logs.
- [ ] A test proves a second user does not see the first user's items.
- [ ] After `bench migrate`, **Test for my user** shows the expected count and items.
