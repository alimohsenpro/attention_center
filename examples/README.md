# Examples

## `sample_app`: a consumer app's side of the source contract

The files a Frappe app adds to plug its lists into Attention Center, as described in
[`docs/PROVIDER_CONTRACT.md`](../docs/PROVIDER_CONTRACT.md). Nothing else of the app is here.

| File | What it shows |
|---|---|
| [`sample_app/hooks.py`](sample_app/hooks.py) | Two entries of `attention_sources`: the declarative "My Requests" (open requests assigned to the user) and the python "Team Queue" (unassigned open requests of the user's teams) |
| [`sample_app/attention.py`](sample_app/attention.py) | The python source: its count, its items, the users to nudge when a request changes, and a nudge for changes that raise no document event, guarded so that the app runs without Attention Center |

Both sources read a `Sample Request` DocType, which the app would ship:

| Field | Type |
|---|---|
| `subject` | Data |
| `status` | Select: `Open`, `Closed` |
| `priority` | Select: `Low`, `Medium`, `High`, `Critical` |
| `due_date` | Date |
| `team` | Link to User Group |
| `assigned_to` | Link to User |

`attention_center/tests/test_examples.py` creates that DocType, makes the sample app look installed
(importable from this folder and listed among the site's apps, so Frappe reads its `hooks.py`),
syncs its entries, and checks what each user sees, who is nudged, and that the app imports nothing from
`attention_center`:

```bash
cd ~/frappe-bench
bench --site test_site run-tests --module attention_center.tests.test_examples
```

To start your own source, copy the entry and the functions you need into your app and rename the key
prefix, the dotted paths and the DocType.
