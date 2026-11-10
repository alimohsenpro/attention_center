# Build pipeline — operator runbook

Attention Center is built by two Claude Managed Agents that run on a schedule in the Claude
Console. Nothing runs on the operator's machine after setup. The Arabic step-by-step setup is in
`docs/SETUP_GUIDE_AR.md`; this file explains the mechanism.

## How it works

```
 every 30 min                         every 30 min (offset)
┌──────────────┐                     ┌───────────────┐
│ ac-builder   │  push task/<ID>     │ ac-reviewer   │
│ (Sonnet 5.5) │ ───────────────►    │ (Opus 5.5)    │
└──────┬───────┘   pull request      └──────┬────────┘
       │                                    │ commit status "agent-review" + squash merge
       ▼                                    ▼
   merge gate:  CI job "tests" green  AND  status "agent-review" = success, on the exact commit
```

- Each scheduled run is a fresh session in a fresh sandbox with the repository mounted.
- Every session first runs `python3 scripts/pipeline/status.py next --role <role>`. That script reads GitHub (pull requests, CI runs, commit statuses, owner comments) and prints one action. Agents never decide by themselves what to work on, whether CI passed or whether a change may be merged.
- One task = one branch `task/<ID>` = one pull request. Only one pull request is open at a time. Order and dependencies come from `pipeline/tasks.json`; briefs from `docs/DELIVERY_PLAN.md`.
- A pull request titled `WIP: …` is claimed by a running builder session. If it shows no activity for 45 minutes another run resumes it.
- The builder cannot approve its own work: its token cannot post commit statuses, and a merge needs the `agent-review` status and a green `tests` run on the exact commit.
- The reviewer posts its review as a pull request comment, sets the status, and merges through `status.py merge`, which refuses unless CI is green and the review status is `success` for the head commit.

## Actions

| Builder action | Meaning |
|---|---|
| IMPLEMENT / RESUME | work on a task and submit the pull request |
| FIX_CI | CI failed; the log tail is in the CI comment on the pull request |
| ADDRESS_REVIEW | the reviewer requested changes |
| WAIT | CI running, review pending, or another run is working |
| STUCK | five failed attempts on one pull request: the builder opens a `[pipeline-halt]` issue |
| HALT | an open `[pipeline-halt]` issue stops both agents until it is closed |
| DONE | every task is merged |

Reviewer actions: REVIEW, MERGE, NOTHING, HALT.

## Controlling it

- Pause or resume: `pipeline/deployments.sh pause` / `unpause`, or the Deployments page in the Console.
- Start a run now: `pipeline/deployments.sh run builder` (or `reviewer`).
- Watch: Console → Managed Agents → Sessions (transcript, tool calls, cost per session).
- Stop everything for a question: open an issue whose title starts with `[pipeline-halt]`. Close it to continue.
- Answer an agent's question: comment on its `[needs-human]` issue. Only comments by the repository owner are read.
- Let a stuck pull request try again: comment `/retry` on the pull request (resets the attempt counter), then close the halt issue.

## Costs and limits

- Each run has a hard budget: builder USD 10, reviewer USD 3 (set on the deployments). A session that hits its cap pauses; the next run resumes from what was pushed.
- Runs that find nothing to do end after one command and cost a few cents.
- The workspace spend limit in the Console is the overall ceiling. Set it before unpausing.
- The builder's model is set in `pipeline/agents/builder.md`. To change it, edit the `model` block and run `ant apply pipeline/agents/builder.md`; the next run uses the new version.

## Who enforces the gate

- **With GitHub branch protection on `main`** (recommended: require a pull request, and the status checks `tests` and `agent-review`, with no bypass): GitHub itself refuses any other merge or push.
- **Without it:** `status.py merge` enforces the same two conditions, and every run verifies `main` after the fact. If the last merged task pull request lacks the reviewer's approval, or a commit reached `main` outside the pipeline, the coordinator opens a `[pipeline-halt]` issue that explains how to accept or revert the change, and both agents stop until it is closed. This detects a bypass; it cannot prevent one.

## Operator changes

- Without branch protection: push to `main` with a commit subject that starts with `ops:`. Any other direct commit trips the check above. To accept a commit after the fact, list its full SHA in `pipeline/accepted_commits.txt` in an `ops:` commit.
- With branch protection: pause the deployments, untick "Do not allow bypassing the above settings" in the branch rule, push, tick it again, unpause.
- Changing an agent's model needs no push: edit the `model` block locally, run `ant apply --yes pipeline/agents/<role>.md`, and restore the file with `git checkout` when you return to the default.
- Issues opened by the agents are created with your own account, and GitHub does not email you about your own activity unless "Include your own updates" is enabled under Settings → Notifications → Email.

## What the agents cannot touch

`.github/workflows/`, `pipeline/`, `scripts/pipeline/` and the audio files are protected by
instruction and by review; the workflow files are additionally protected because the agents'
tokens lack the Workflows permission. Changing any of them is an operator task.

## Security notes for a public repository

- Restrict interactions to collaborators (Settings → Moderation → Interaction limits) so strangers cannot open issues or pull requests.
- `status.py` ignores every pull request, comment, issue and status that was not created by the repository owner or by GitHub Actions.
- No secret is stored in the repository. Tokens live in the Console (vault credentials and deployment resources). `claude-lock.json` and `.pipeline-deployments` hold only resource ids and are git-ignored.
- Skills under `.claude/skills/` and this repository's instructions are loaded by the agents at session start; they change only through reviewed pull requests.
