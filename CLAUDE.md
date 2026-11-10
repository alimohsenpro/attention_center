# Attention Center — engineering manual for agents

Attention Center is a Frappe 15 app that shows every desk user what is waiting on them across
all installed apps, and interrupts them (badge, toast, sound) only when it is deserved. It is
built by an unattended pipeline; this file is what every working session needs to know.

## Documents

| File | Use it for |
|---|---|
| `docs/PRD.md` | What to build. Requirement IDs and acceptance criteria. Wins on conflict |
| `docs/TECH_DESIGN.md` | How: data model, source contract, API, realtime, client architecture, tests |
| `docs/DELIVERY_PLAN.md` | Task briefs and the definition of done. Read your task with `python3 scripts/pipeline/status.py brief <ID>` |
| `docs/DECISIONS.md` | Decisions already taken by the product owner, and the log of agent decisions |
| `docs/DESIGN_TOKENS.md` | Colours, spacing, component look |
| `docs/SANDBOX.md` | How the bench behaves in the cloud sandbox (written by task M0-T1) |
| `pipeline/README.md` | How the pipeline works (for the human operator) |

Read the sections your task cites. Do not read every document end to end in every session.

## Commands

```bash
bash scripts/dev/bench_up.sh                      # bench at ~/frappe-bench, site test_site, this repo linked as the app
bash scripts/ci/run_tests.sh                      # everything CI runs; must pass before you submit
cd ~/frappe-bench
bench --site test_site run-tests --module attention_center.tests.test_install   # one module
bench --site test_site run-tests --app attention_center --failfast
bench --site test_site migrate                    # after changing a DocType JSON or hooks
bench build --app attention_center                # after changing client code
bench --site test_site console                    # quick experiments
```

Creating or changing a DocType: set `developer_mode` on `test_site`
(`bench --site test_site set-config developer_mode 1`), create or edit the DocType through
`frappe.get_doc({...}).insert()` / `.save()` in the console so Frappe writes the canonical JSON
into the app, then review the exported files before committing. Hand-written DocType JSON is
acceptable only if `bench migrate` round-trips it without changes.

## Rules that are never traded away

1. **Permissions.** Everything a user sees is computed on the server as that user. Use `frappe.get_list` (permission-aware) for user-facing queries; `frappe.get_all`, `frappe.db.sql`, `frappe.db.count` and `ignore_permissions=True` are allowed only where the design names them, with a comment saying why it is safe. No endpoint takes a user id from the client. Admin settings may hide things, never reveal them.
2. **Privacy.** No item content in logs, caches shared between users, realtime payloads or stored documents. Log source keys, user ids, counts, durations.
3. **Isolation.** The client lives in one Shadow DOM host. No dependency on Frappe's navbar or bell, no Bootstrap classes, no global CSS, no changes to core behaviour. A failure in this app must never break the desk.
4. **Self-contained.** The only dependency is `frappe`. No CDN, no external request at runtime, no new Python or npm package.
5. **Generic.** No organisation names, hosts, people, data or credentials anywhere in the repository, including tests, fixtures, comments and commit messages. Use neutral sample data.
6. **Protected paths.** Do not edit `.github/workflows/`, `pipeline/`, `scripts/pipeline/`, or the audio files in `attention_center/public/sounds/` (regenerate them only by changing `scripts/sounds/generate_tones.py` in a task that asks for it).

## Code conventions

- SOLID, KISS, YAGNI. Build what the task asks; no speculative options, layers or abstractions.
- Comments are rare and explain why, never what. No commented-out code, no TODOs without an entry under "Follow-ups" in the pull request.
- Python: formatted and linted by ruff as configured in `pyproject.toml` (tabs, 110 columns). Type hints on public functions. Parameterised queries only. Raise Frappe exceptions (`frappe.PermissionError`, `frappe.ValidationError`) with translatable messages.
- JavaScript: ES modules, no framework. Pure logic (policy, coalescing, coordination, formatting) lives in modules with no DOM or `frappe` access so it can be tested with `node --test`. Render text with `textContent` or the escape helper, never by concatenating untrusted strings into HTML. CSS uses logical properties only (`inline-start`, `inline-end`, `block-*`) so one stylesheet serves RTL and LTR.
- Frappe 15 specifics: test base class is `frappe.tests.utils.FrappeTestCase` (not `IntegrationTestCase`, which is Frappe 16). Confirm framework behaviour in `~/frappe-bench/apps/frappe` rather than from memory.

## Translations

Source strings are English, wrapped with `_("...")` in Python and `__("...")` in JavaScript, with
placeholders instead of concatenation: `_("{0} new items").format(n)`, `__("{0} new items", [n])`.
Every user-visible string gets a simple, familiar Arabic translation in
`attention_center/translations/ar.csv`, one per line: `"source","translation",""`. Prefer the
words an office employee already uses (for example «ما يحتاج انتباهك», «موافقات», «تكليفات»,
«للعلم», «عاجل», «فوري», «متأخر», «فتح», «عرض الكل», «كتم», «عدم الإزعاج»).

## Tests

A test exists to turn red when the behaviour breaks.

- Assert observable behaviour, not that a mock was called. Do not mock the unit under test.
- Each test creates the users, roles and documents it needs and relies on nothing already in the site. `FrappeTestCase` rolls the transaction back.
- Every permission rule has a negative test: a second user who must not see the item, and an assertion that they do not.
- Table-driven tests for the alert policy and the coordinator logic.
- If you cannot make a behaviour testable, say so in the pull request description; do not write a test that cannot fail.

## Commits and pull requests

- Small commits in Conventional Commits style: `feat(engine): …`, `fix(api): …`, `test: …`, `docs: …`.
- The pull request description (passed to `status.py submit --body-file`) has four short sections: **What changed**, **Requirements covered** (IDs), **How it was tested** (commands and results), **Follow-ups / deferred**.

## Decisions and escalation

Reversible choice: decide, and add a line under "Agent decisions" in `docs/DECISIONS.md`
(`date — task — decision — why`). Product-shaping, permission-weakening or irreversible choice:
escalate with `python3 scripts/pipeline/status.py escalate` as your instructions describe. Never
reopen a decision listed in `docs/DECISIONS.md`.
