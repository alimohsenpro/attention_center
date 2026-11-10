# Attention Center

A Frappe app that shows every desk user **what needs them now** across all installed apps —
approvals, assignments, shared unit queues, notifications — and interrupts them with a badge, a
toast or a sound only when it is deserved.

- One floating launcher and one window on every desk page, isolated from desk themes.
- Sources are pluggable: define one from the desk (a DocType, filters and a few field mappings) or ship Python callables from your app through a hook. Your app keeps working without Attention Center.
- Everything is computed live, as the logged-in user, from the source app. No copies, no second "read" state.
- Arabic (RTL) and English, light and dark.

**Status:** under construction. Requirements are in `docs/PRD.md`, the design in
`docs/TECH_DESIGN.md`, the plan in `docs/DELIVERY_PLAN.md`.

## Install

```bash
cd /path/to/your/bench
bench get-app <repository url> --branch main
bench --site <site> install-app attention_center
```

Requires Frappe 15.

## Development

See `CLAUDE.md` for commands and conventions. `bash scripts/dev/bench_up.sh` builds a test
bench; `bash scripts/ci/run_tests.sh` runs everything CI runs.

## Licence

MIT. Third-party skill files under `.claude/skills/` keep their own licences, listed in
`.claude/skills/NOTICE.md`.
