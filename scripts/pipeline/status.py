#!/usr/bin/env python3
"""Deterministic coordinator for the build pipeline.

Agents never decide what to work on, whether CI passed, or whether a PR may be merged.
They run this script, which derives everything from GitHub state, and follow its output.

Environment:
  AC_GITHUB_TOKEN  GitHub token (in cloud sessions: a vault placeholder substituted at egress)
  AC_REPO          optional "owner/name"; default: parsed from `git remote get-url origin`

Only content written by the repository owner or by GitHub Actions is ever printed back to an
agent. Text from anyone else is ignored: the repository is public.

Standard library only. HTTP goes through `curl` so that vault credential substitution, which
is documented for curl, applies.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_FILE = REPO_ROOT / "pipeline" / "tasks.json"
PLAN_FILE = REPO_ROOT / "docs" / "DELIVERY_PLAN.md"

BASE_BRANCH = "main"
WIP_PREFIX = "WIP: "
REVIEW_CONTEXT = "agent-review"
CI_WORKFLOW_NAME = "CI"
CI_BOT = "github-actions[bot]"
CLAIM_FRESH_MINUTES = 45
CI_MISSING_MINUTES = 30
MAX_ATTEMPTS = 5
MAX_RUNS_PER_TASK = 6
RUN_MARKER = "<!-- ac:run -->"
HALT_PREFIX = "[pipeline-halt]"
OPS_PREFIX = "ops:"
ACCEPTED_FILE = REPO_ROOT / "pipeline" / "accepted_commits.txt"
HUMAN_PREFIX = "[needs-human]"
REVIEW_MARKER = "<!-- ac:review state={state} sha={sha} -->"
REVIEW_MARKER_RE = re.compile(r"<!-- ac:review state=(success|failure) sha=([0-9a-f]{7,40}) -->")
HEARTBEAT_RE = re.compile(r"\n?<!-- ac:heartbeat [^>]* -->")
CI_FAILED = {"failure", "cancelled", "timed_out", "startup_failure", "action_required"}


class PipelineError(Exception):
	pass


# ---------------------------------------------------------------- GitHub transport


class GitHub:
	def __init__(self, repo: str, token: str, runner=subprocess.run):
		self.repo = repo
		self.token = token
		self._run = runner

	def request(self, method: str, path: str, body: dict | None = None, params: dict | None = None):
		url = "https://api.github.com" + path
		if params:
			url += "?" + urllib.parse.urlencode(params)
		headers = "\n".join(
			[
				f"Authorization: Bearer {self.token}",
				"Accept: application/vnd.github+json",
				"X-GitHub-Api-Version: 2022-11-28",
				"User-Agent: attention-center-pipeline",
				"",
			]
		)
		# Headers go through stdin so the token never appears in the process list.
		cmd = ["curl", "-sS", "--max-time", "60", "-X", method, "-H", "@-", "-w", "\n%{http_code}", url]
		if body is not None:
			cmd += ["--data-binary", json.dumps(body)]
		proc = self._run(cmd, input=headers, capture_output=True, text=True)
		if proc.returncode != 0:
			raise PipelineError(f"curl failed ({proc.returncode}): {proc.stderr.strip()[:300]}")
		text, _, code = proc.stdout.rpartition("\n")
		status = int(code or 0)
		data = json.loads(text) if text.strip() else None
		if status >= 400:
			message = data.get("message") if isinstance(data, dict) else text[:300]
			raise PipelineError(f"GitHub {method} {path} -> {status}: {message}")
		return data

	def get(self, path: str, **params):
		return self.request("GET", f"/repos/{self.repo}{path}", params=params or None)

	def post(self, path: str, body: dict):
		return self.request("POST", f"/repos/{self.repo}{path}", body=body)

	def patch(self, path: str, body: dict):
		return self.request("PATCH", f"/repos/{self.repo}{path}", body=body)

	def put(self, path: str, body: dict):
		return self.request("PUT", f"/repos/{self.repo}{path}", body=body)

	def delete(self, path: str):
		return self.request("DELETE", f"/repos/{self.repo}{path}")

	def paged(self, path: str, max_pages: int = 3, **params):
		out = []
		for page in range(1, max_pages + 1):
			chunk = self.get(path, per_page=100, page=page, **params) or []
			out.extend(chunk)
			if len(chunk) < 100:
				break
		return out


# ---------------------------------------------------------------- pure helpers


def parse_time(value: str) -> datetime:
	return datetime.fromisoformat(value.replace("Z", "+00:00"))


def minutes_since(value: str, now: datetime) -> float:
	return (now - parse_time(value)).total_seconds() / 60


def parse_repo(remote_url: str) -> str:
	match = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", remote_url.strip())
	if not match:
		raise PipelineError(f"Cannot parse a GitHub repository from remote URL: {remote_url!r}")
	return f"{match.group(1)}/{match.group(2)}"


def load_tasks(path: Path = TASKS_FILE) -> list[dict]:
	return json.loads(path.read_text(encoding="utf-8"))["tasks"]


def task_branch(task_id: str) -> str:
	return f"task/{task_id}"


def task_from_branch(branch: str) -> str | None:
	match = re.fullmatch(r"task/(M\d+-T\d+)", branch or "")
	return match.group(1) if match else None


def task_brief(task_id: str, plan_text: str) -> str:
	match = re.search(rf"^### {re.escape(task_id)} — .*$", plan_text, flags=re.M)
	if not match:
		raise PipelineError(f"Task {task_id} not found in docs/DELIVERY_PLAN.md")
	rest = plan_text[match.start() :]
	nxt = re.search(r"^### ", rest[match.end() - match.start() :], flags=re.M)
	return (rest[: match.end() - match.start() + nxt.start()] if nxt else rest).strip()


def pr_title(task: dict, wip: bool) -> str:
	return f"{WIP_PREFIX if wip else ''}[{task['id']}] {task['title']}"


@dataclass
class OpenPR:
	number: int
	task: str
	sha: str
	wip: bool
	idle_minutes: float
	ci: str  # success | failure | pending | missing
	review: str  # success | failure | none
	attempts: int
	url: str = ""
	runs: int = 0  # builder sessions that started work on this PR since the last /retry


@dataclass
class State:
	tasks: list[dict]
	merged: set[str] = field(default_factory=set)
	open_pr: OpenPR | None = None
	halt_reason: str | None = None
	integrity_problem: str | None = None


def next_task(state: State) -> dict | None:
	for task in state.tasks:
		if task["id"] in state.merged:
			continue
		if all(dep in state.merged for dep in task["depends_on"]):
			return task
		return None  # strictly ordered: an unmet dependency blocks the queue
	return None


def decide_builder(state: State) -> dict:
	if state.halt_reason:
		return {"action": "HALT", "reason": state.halt_reason}
	pr = state.open_pr
	if pr:
		base = {"task": pr.task, "branch": task_branch(pr.task), "pr": pr.number, "sha": pr.sha}
		too_many_runs = pr.runs >= MAX_RUNS_PER_TASK
		if pr.wip:
			if pr.idle_minutes < CLAIM_FRESH_MINUTES:
				return {"action": "WAIT", "reason": "another run is working on this PR", **base}
			if too_many_runs:
				return {"action": "STUCK", "reason": f"{pr.runs} sessions without finishing the task", **base}
			return {"action": "RESUME", "reason": "previous run stopped before submitting", **base}
		if pr.ci == "pending":
			return {"action": "WAIT", "reason": "CI is running", **base}
		if pr.ci in ("failure", "missing") or pr.review == "failure":
			if pr.attempts >= MAX_ATTEMPTS:
				return {"action": "STUCK", "reason": f"{pr.attempts} failed attempts", **base}
			if too_many_runs:
				return {"action": "STUCK", "reason": f"{pr.runs} sessions without finishing the task", **base}
			if pr.ci == "failure":
				return {"action": "FIX_CI", "reason": "CI failed on the PR head", **base}
			if pr.ci == "missing":
				return {"action": "FIX_CI", "reason": "no CI run found for the PR head; push again", **base}
			return {"action": "ADDRESS_REVIEW", "reason": "reviewer requested changes", **base}
		if pr.review == "none":
			return {"action": "WAIT", "reason": "awaiting review", **base}
		return {"action": "WAIT", "reason": "approved; awaiting merge", **base}
	task = next_task(state)
	if task:
		return {
			"action": "IMPLEMENT",
			"task": task["id"],
			"title": task["title"],
			"branch": task_branch(task["id"]),
			"reason": "next task in order",
		}
	if all(t["id"] in state.merged for t in state.tasks):
		return {"action": "DONE", "reason": "every task is merged"}
	return {"action": "HALT", "reason": "no task is startable; check dependencies in pipeline/tasks.json"}


def decide_reviewer(state: State) -> dict:
	if state.halt_reason:
		return {"action": "HALT", "reason": state.halt_reason}
	pr = state.open_pr
	if not pr or pr.wip or pr.ci != "success":
		return {"action": "NOTHING", "reason": "no PR is ready for review"}
	base = {"task": pr.task, "branch": task_branch(pr.task), "pr": pr.number, "sha": pr.sha}
	if pr.review == "none":
		return {"action": "REVIEW", "reason": "CI passed; not reviewed at this commit", **base}
	if pr.review == "success":
		return {"action": "MERGE", "reason": "approved but not merged yet", **base}
	return {"action": "NOTHING", "reason": "changes requested; waiting for the builder", **base}


def ci_state(runs: list[dict], head_age_minutes: float) -> str:
	runs = [r for r in runs if r.get("name") == CI_WORKFLOW_NAME and r.get("event") == "pull_request"]
	if not runs:
		return "pending" if head_age_minutes < CI_MISSING_MINUTES else "missing"
	latest = max(runs, key=lambda r: r["created_at"])
	if latest["status"] != "completed":
		return "pending"
	if latest["conclusion"] == "success":
		return "success"
	return "failure" if latest["conclusion"] in CI_FAILED else "pending"


def review_state(statuses: list[dict], owner: str) -> str:
	mine = [s for s in statuses if s.get("context") == REVIEW_CONTEXT and s["creator"]["login"] == owner]
	if not mine:
		return "none"
	latest = max(mine, key=lambda s: s["created_at"])
	return latest["state"] if latest["state"] in ("success", "failure") else "none"


def retry_time(comments: list[dict], owner: str) -> str:
	return max(
		(
			c["created_at"]
			for c in comments
			if c["user"]["login"] == owner and c["body"].strip().startswith("/retry")
		),
		default="",
	)


def count_runs(comments: list[dict], owner: str) -> int:
	"""Builder sessions that started work on the PR since the owner's last `/retry` comment."""
	since = retry_time(comments, owner)
	return sum(
		1
		for c in comments
		if c["user"]["login"] == owner and RUN_MARKER in c["body"] and c["created_at"] > since
	)


def count_attempts(failed_ci_runs: list[dict], comments: list[dict], owner: str) -> int:
	"""Failed CI runs plus failed reviews since the owner's last `/retry` comment."""
	retry_at = max(
		(
			c["created_at"]
			for c in comments
			if c["user"]["login"] == owner and c["body"].strip().startswith("/retry")
		),
		default="",
	)
	failed_reviews = [
		c
		for c in comments
		if c["user"]["login"] == owner
		and (m := REVIEW_MARKER_RE.search(c["body"]))
		and m.group(1) == "failure"
		and c["created_at"] > retry_at
	]
	failed_ci = [r for r in failed_ci_runs if r["created_at"] > retry_at]
	return len(failed_ci) + len(failed_reviews)


def accepted_commits(path: Path = ACCEPTED_FILE) -> set[str]:
	if not path.exists():
		return set()
	lines = (line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines())
	return {line for line in lines if line}


def integrity_problem(gh: GitHub, merged_pulls: list[dict], owner: str, accepted: set[str]) -> str | None:
	"""GitHub does not protect `main` here, so verify after the fact that nothing bypassed the gates.

	The last merged task PR must carry the reviewer's approval, and every commit that reached
	`main` after it must be an operator commit (subject starting with `ops:`) or accepted.
	"""
	if not merged_pulls:
		return None
	latest = max(merged_pulls, key=lambda pull: pull["merged_at"])
	statuses = gh.get(f"/commits/{latest['head']['sha']}/statuses", per_page=100) or []
	if review_state(statuses, owner) != "success" and latest.get("merge_commit_sha") not in accepted:
		return f"pull request #{latest['number']} was merged without the reviewer's approval"
	commits = gh.get("/commits", sha=BASE_BRANCH, per_page=30) or []
	shas = [commit["sha"] for commit in commits]
	if latest.get("merge_commit_sha") not in shas:
		return None
	for commit in commits[: shas.index(latest["merge_commit_sha"])]:
		subject = commit["commit"]["message"].split("\n", 1)[0]
		if not subject.startswith(OPS_PREFIX) and commit["sha"] not in accepted:
			return f"commit {commit['sha'][:10]} reached {BASE_BRANCH} outside the pipeline"
	return None


# ---------------------------------------------------------------- state collection


def collect_state(gh: GitHub, tasks: list[dict], now: datetime | None = None) -> State:
	now = now or datetime.now(timezone.utc)
	owner = gh.repo.split("/")[0]
	state = State(tasks=tasks)

	issues = gh.paged("/issues", state="open", creator=owner)
	halts = [i for i in issues if "pull_request" not in i and i["title"].lower().startswith(HALT_PREFIX)]
	if halts:
		state.halt_reason = f"open issue #{halts[0]['number']}: {halts[0]['title']}"

	pulls = gh.paged("/pulls", state="all", sort="created", direction="desc")
	open_pulls = []
	merged_pulls = []
	for pull in pulls:
		task_id = task_from_branch(pull["head"]["ref"])
		same_repo = (pull["head"].get("repo") or {}).get("full_name") == gh.repo
		if not task_id or not same_repo or pull["user"]["login"] != owner:
			continue
		if pull.get("merged_at"):
			state.merged.add(task_id)
			merged_pulls.append(pull)
		elif pull["state"] == "open":
			open_pulls.append((task_id, pull))

	if not state.halt_reason:
		state.integrity_problem = integrity_problem(gh, merged_pulls, owner, accepted_commits())
		state.halt_reason = state.integrity_problem

	if open_pulls:
		task_id, pull = min(open_pulls, key=lambda item: item[1]["number"])
		sha = pull["head"]["sha"]
		commit = gh.get(f"/commits/{sha}")
		head_age = minutes_since(commit["commit"]["committer"]["date"], now)
		idle = min(head_age, minutes_since(pull["updated_at"], now))
		runs = (gh.get("/actions/runs", head_sha=sha, per_page=30) or {}).get("workflow_runs", [])
		statuses = gh.get(f"/commits/{sha}/statuses", per_page=100) or []
		comments = gh.paged(f"/issues/{pull['number']}/comments")
		failed_runs = (
			gh.get(
				"/actions/runs",
				branch=pull["head"]["ref"],
				event="pull_request",
				status="failure",
				per_page=50,
			)
			or {}
		).get("workflow_runs", [])
		state.open_pr = OpenPR(
			number=pull["number"],
			task=task_id,
			sha=sha,
			wip=pull["title"].startswith(WIP_PREFIX),
			idle_minutes=idle,
			ci=ci_state(runs, head_age),
			review=review_state(statuses, owner),
			attempts=count_attempts(failed_runs, comments, owner),
			url=pull["html_url"],
			runs=count_runs(comments, owner),
		)
	return state


# ---------------------------------------------------------------- commands


def git(*args: str, check: bool = True) -> str:
	proc = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
	if check and proc.returncode != 0:
		raise PipelineError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:400]}")
	return proc.stdout.strip()


def find_task(tasks: list[dict], task_id: str) -> dict:
	for task in tasks:
		if task["id"] == task_id:
			return task
	raise PipelineError(f"Unknown task id: {task_id}")


def find_open_pr(gh: GitHub, task_id: str) -> dict | None:
	owner = gh.repo.split("/")[0]
	pulls = gh.get("/pulls", state="open", head=f"{owner}:{task_branch(task_id)}", per_page=5) or []
	return pulls[0] if pulls else None


def ensure_git_identity() -> None:
	"""A fresh sandbox has no git identity; commits need one."""
	if not git("config", "user.email", check=False):
		git("config", "user.name", "attention-center-pipeline")
		git("config", "user.email", "attention-center-pipeline@users.noreply.github.com")


def cmd_start(gh: GitHub, tasks: list[dict], args) -> dict:
	"""Check out the task branch, make sure a WIP pull request exists, and claim it."""
	task = find_task(tasks, args.task)
	branch = task_branch(task["id"])
	ensure_git_identity()
	git("fetch", "origin", "--prune")
	remote_exists = bool(git("ls-remote", "--heads", "origin", branch))
	if remote_exists:
		git("checkout", "-B", branch, f"origin/{branch}")
	else:
		git("checkout", "-B", branch, f"origin/{BASE_BRANCH}")
		git("commit", "--allow-empty", "-m", f"chore({task['id']}): start task")
		git("push", "-u", "origin", branch)
	pull = find_open_pr(gh, task["id"])
	if pull is None:
		body = (
			f"Task **{task['id']} — {task['title']}** (see `docs/DELIVERY_PLAN.md`).\n\n"
			"Work in progress. The description is completed when the task is submitted.\n"
		)
		pull = gh.post(
			"/pulls", {"title": pr_title(task, wip=True), "head": branch, "base": BASE_BRANCH, "body": body}
		)
	elif not pull["title"].startswith(WIP_PREFIX):
		pull = gh.patch(f"/pulls/{pull['number']}", {"title": pr_title(task, wip=True)})
	# One marker per working session: the coordinator stops a task that eats sessions without finishing.
	gh.post(
		f"/issues/{pull['number']}/comments", {"body": f"A builder session started work.\n\n{RUN_MARKER}"}
	)
	return {"ok": True, "task": task["id"], "branch": branch, "pr": pull["number"], "url": pull["html_url"]}


def cmd_heartbeat(gh: GitHub, tasks: list[dict], args) -> dict:
	pull = find_open_pr(gh, args.task)
	if not pull:
		raise PipelineError(f"No open PR for {args.task}")
	stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
	body = HEARTBEAT_RE.sub("", pull.get("body") or "") + f"\n<!-- ac:heartbeat {stamp} -->"
	gh.patch(f"/pulls/{pull['number']}", {"body": body})
	return {"ok": True, "pr": pull["number"], "heartbeat": stamp}


def cmd_submit(gh: GitHub, tasks: list[dict], args) -> dict:
	task = find_task(tasks, args.task)
	pull = find_open_pr(gh, task["id"])
	if not pull:
		raise PipelineError(f"No open PR for {task['id']}")
	if git("status", "--porcelain"):
		raise PipelineError("Working tree is not clean: commit or discard changes before submitting")
	local, remote = git("rev-parse", "HEAD"), git("rev-parse", f"origin/{task_branch(task['id'])}")
	if local != remote:
		raise PipelineError("Local HEAD differs from the pushed branch: push before submitting")
	patch = {"title": pr_title(task, wip=False)}
	if args.body_file:
		patch["body"] = Path(args.body_file).read_text(encoding="utf-8")
	pull = gh.patch(f"/pulls/{pull['number']}", patch)
	return {
		"ok": True,
		"pr": pull["number"],
		"url": pull["html_url"],
		"next": "exit; CI and review run without you",
	}


def trusted_comments(gh: GitHub, number: int, authors: set[str]) -> list[dict]:
	return [c for c in gh.paged(f"/issues/{number}/comments") if c["user"]["login"] in authors]


def cmd_ci_log(gh: GitHub, tasks: list[dict], args) -> str:
	comments = trusted_comments(gh, args.pr, {CI_BOT})
	return comments[-1]["body"] if comments else "No CI comment found on this pull request."


def cmd_review_notes(gh: GitHub, tasks: list[dict], args) -> str:
	owner = gh.repo.split("/")[0]
	notes = [c["body"] for c in trusted_comments(gh, args.pr, {owner}) if REVIEW_MARKER_RE.search(c["body"])]
	return notes[-1] if notes else "No review comment found on this pull request."


def require_head(gh: GitHub, number: int, sha: str) -> dict:
	pull = gh.get(f"/pulls/{number}")
	if pull["head"]["sha"] != sha:
		raise PipelineError(f"PR #{number} head moved to {pull['head']['sha'][:10]}; re-run status")
	return pull


def cmd_verdict(gh: GitHub, tasks: list[dict], args) -> dict:
	pull = require_head(gh, args.pr, args.sha)
	review = Path(args.body_file).read_text(encoding="utf-8").strip()
	marker = REVIEW_MARKER.format(state=args.state, sha=args.sha)
	gh.post(f"/issues/{args.pr}/comments", {"body": f"{review}\n\n{marker}"})
	description = (
		"Approved by the reviewer agent"
		if args.state == "success"
		else "Changes requested by the reviewer agent"
	)
	gh.post(
		f"/statuses/{args.sha}",
		{
			"state": args.state,
			"context": REVIEW_CONTEXT,
			"description": description,
			"target_url": pull["html_url"],
		},
	)
	return {"ok": True, "pr": args.pr, "state": args.state}


def cmd_merge(gh: GitHub, tasks: list[dict], args) -> dict:
	pull = require_head(gh, args.pr, args.sha)
	task_id = task_from_branch(pull["head"]["ref"])
	state = collect_state(gh, tasks)
	if state.halt_reason:
		raise PipelineError(f"Refusing to merge: the pipeline is halted ({state.halt_reason})")
	pr = state.open_pr
	if not pr or pr.number != args.pr or pr.wip or pr.ci != "success" or pr.review != "success":
		raise PipelineError("Refusing to merge: PR must be submitted, CI green and approved at this commit")
	task = find_task(tasks, task_id)
	gh.put(
		f"/pulls/{args.pr}/merge",
		{
			"merge_method": "squash",
			"sha": args.sha,
			"commit_title": f"[{task['id']}] {task['title']} (#{args.pr})",
		},
	)
	try:
		gh.delete(f"/git/refs/heads/{pull['head']['ref']}")
	except PipelineError:
		pass
	return {"ok": True, "merged": args.pr, "task": task_id}


def cmd_escalate(gh: GitHub, tasks: list[dict], args) -> dict:
	prefix = HALT_PREFIX if args.halt else HUMAN_PREFIX
	body = Path(args.body_file).read_text(encoding="utf-8")
	issue = gh.post("/issues", {"title": f"{prefix} {args.title}", "body": body})
	return {"ok": True, "issue": issue["number"], "url": issue["html_url"], "halts_pipeline": bool(args.halt)}


INTEGRITY_BODY = """The pipeline coordinator stopped both agents: {problem}.

`main` is not protected by GitHub in this repository, so the coordinator checks after the fact
that every change passed CI and the reviewer agent. This one did not.

What to do, as the repository owner:

1. Look at the change and decide whether to keep it or revert it.
2. To keep a pull request that was merged without approval, review it and then record your
   approval: `python3 scripts/pipeline/status.py verdict --pr <n> --sha <head sha> --state success --body-file <file>`.
3. To keep a commit that was pushed straight to `main`, add its full SHA on a line of
   `pipeline/accepted_commits.txt` in a commit whose subject starts with `ops:`.
4. Close this issue. The agents resume at their next scheduled run.
"""


def report_integrity_problem(gh: GitHub, problem: str) -> None:
	"""Leave a visible, pipeline-halting record. Later runs see the open issue and stop there."""
	try:
		gh.post(
			"/issues", {"title": f"{HALT_PREFIX} {problem}", "body": INTEGRITY_BODY.format(problem=problem)}
		)
	except PipelineError:
		pass


def cmd_decisions(gh: GitHub, tasks: list[dict], args) -> str:
	owner = gh.repo.split("/")[0]
	out = []
	for issue in gh.paged("/issues", state="all", creator=owner, since=args.since or "2026-01-01T00:00:00Z"):
		if "pull_request" in issue or not issue["title"].lower().startswith(HUMAN_PREFIX):
			continue
		answers = [c["body"] for c in trusted_comments(gh, issue["number"], {owner})]
		out.append(
			f"## #{issue['number']} {issue['title']} ({issue['state']})\n"
			+ ("\n---\n".join(answers) or "(no answer yet)")
		)
	return "\n\n".join(out) or "No decision issues."


def cmd_seed_review_status(gh: GitHub, tasks: list[dict], args) -> dict:
	"""One-time, by the operator: make the review context selectable in branch protection."""
	sha = gh.get(f"/branches/{BASE_BRANCH}")["commit"]["sha"]
	gh.post(
		f"/statuses/{sha}",
		{"state": "success", "context": REVIEW_CONTEXT, "description": "Seeded so the check can be required"},
	)
	return {"ok": True, "context": REVIEW_CONTEXT, "sha": sha}


def cmd_doctor(gh: GitHub, tasks: list[dict], args) -> dict:
	repo = gh.request("GET", f"/repos/{gh.repo}")
	branch = gh.get(f"/branches/{BASE_BRANCH}")
	return {
		"repo": repo["full_name"],
		"visibility": repo.get("visibility"),
		"default_branch": repo["default_branch"],
		"main_protected": branch.get("protected"),
		"permissions": repo.get("permissions"),
		"tasks": len(tasks),
	}


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
	sub = parser.add_subparsers(dest="command", required=True)
	sub.add_parser("next", help="what should this run do").add_argument(
		"--role", choices=["builder", "reviewer"], required=True
	)
	sub.add_parser("state", help="dump the derived pipeline state")
	sub.add_parser("brief", help="print a task's brief").add_argument("task")
	for name in ("start", "heartbeat"):
		sub.add_parser(name).add_argument("--task", required=True)
	submit = sub.add_parser("submit")
	submit.add_argument("--task", required=True)
	submit.add_argument("--body-file")
	for name in ("ci-log", "review-notes"):
		sub.add_parser(name).add_argument("--pr", type=int, required=True)
	verdict = sub.add_parser("verdict")
	verdict.add_argument("--pr", type=int, required=True)
	verdict.add_argument("--sha", required=True)
	verdict.add_argument("--state", choices=["success", "failure"], required=True)
	verdict.add_argument("--body-file", required=True)
	merge = sub.add_parser("merge")
	merge.add_argument("--pr", type=int, required=True)
	merge.add_argument("--sha", required=True)
	escalate = sub.add_parser("escalate")
	escalate.add_argument("--title", required=True)
	escalate.add_argument("--body-file", required=True)
	escalate.add_argument(
		"--halt", action="store_true", help="stop the whole pipeline until the issue is closed"
	)
	sub.add_parser("decisions").add_argument("--since")
	sub.add_parser("seed-review-status")
	sub.add_parser("doctor")
	return parser


COMMANDS = {
	"start": cmd_start,
	"heartbeat": cmd_heartbeat,
	"submit": cmd_submit,
	"ci-log": cmd_ci_log,
	"review-notes": cmd_review_notes,
	"verdict": cmd_verdict,
	"merge": cmd_merge,
	"escalate": cmd_escalate,
	"decisions": cmd_decisions,
	"seed-review-status": cmd_seed_review_status,
	"doctor": cmd_doctor,
}


def main(argv: list[str] | None = None) -> int:
	import os

	args = build_parser().parse_args(argv)
	try:
		tasks = load_tasks()
		if args.command == "brief":
			print(task_brief(args.task, PLAN_FILE.read_text(encoding="utf-8")))
			return 0
		token = os.environ.get("AC_GITHUB_TOKEN")
		if not token:
			raise PipelineError("AC_GITHUB_TOKEN is not set")
		repo = os.environ.get("AC_REPO") or parse_repo(git("remote", "get-url", "origin"))
		gh = GitHub(repo, token)
		if args.command == "next":
			state = collect_state(gh, tasks)
			if state.integrity_problem:
				report_integrity_problem(gh, state.integrity_problem)
			result = decide_builder(state) if args.role == "builder" else decide_reviewer(state)
		elif args.command == "state":
			state = collect_state(gh, tasks)
			result = {
				"merged": sorted(state.merged),
				"open_pr": state.open_pr and vars(state.open_pr),
				"halt": state.halt_reason,
			}
		else:
			result = COMMANDS[args.command](gh, tasks, args)
		print(result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False))
		return 0
	except PipelineError as exc:
		print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
		return 1


if __name__ == "__main__":
	sys.exit(main())
