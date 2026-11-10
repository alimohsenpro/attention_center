"""Unit tests for the pipeline coordinator. Run: python3 -m unittest scripts/pipeline/test_status.py"""

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import status as s

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
TASKS = [
	{"id": "M0-T1", "title": "Sandbox", "depends_on": []},
	{"id": "M1-T1", "title": "DocTypes", "depends_on": ["M0-T1"]},
	{"id": "M1-T2", "title": "Registry", "depends_on": ["M1-T1"]},
]
OWNER = "owner"
REPO = "owner/repo"


def ago(minutes: float) -> str:
	return (NOW - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def open_pr(**overrides) -> s.OpenPR:
	base = dict(
		number=7,
		task="M1-T1",
		sha="a" * 40,
		wip=False,
		idle_minutes=5,
		ci="success",
		review="none",
		attempts=0,
	)
	return s.OpenPR(**{**base, **overrides})


class DecideBuilderTest(unittest.TestCase):
	def act(self, **kwargs):
		return s.decide_builder(s.State(tasks=TASKS, **kwargs))["action"]

	def test_first_task_when_nothing_exists(self):
		result = s.decide_builder(s.State(tasks=TASKS))
		self.assertEqual(
			(result["action"], result["task"], result["branch"]), ("IMPLEMENT", "M0-T1", "task/M0-T1")
		)

	def test_next_task_follows_merged_dependencies(self):
		result = s.decide_builder(s.State(tasks=TASKS, merged={"M0-T1"}))
		self.assertEqual(result["task"], "M1-T1")

	def test_done_only_when_every_task_is_merged(self):
		self.assertEqual(self.act(merged={"M0-T1", "M1-T1", "M1-T2"}), "DONE")
		self.assertNotEqual(self.act(merged={"M0-T1", "M1-T1"}), "DONE")

	def test_unmet_dependency_blocks_the_queue_instead_of_skipping_ahead(self):
		tasks = [
			{"id": "M1-T1", "title": "x", "depends_on": ["M9-T9"]},
			{"id": "M1-T2", "title": "y", "depends_on": []},
		]
		self.assertEqual(s.decide_builder(s.State(tasks=tasks))["action"], "HALT")

	def test_halt_issue_wins_over_everything(self):
		self.assertEqual(self.act(halt_reason="open issue #3", open_pr=open_pr(ci="failure")), "HALT")

	def test_fresh_wip_pr_is_left_to_the_run_that_claimed_it(self):
		self.assertEqual(self.act(open_pr=open_pr(wip=True, idle_minutes=s.CLAIM_FRESH_MINUTES - 1)), "WAIT")

	def test_stale_wip_pr_is_resumed(self):
		self.assertEqual(
			self.act(open_pr=open_pr(wip=True, idle_minutes=s.CLAIM_FRESH_MINUTES + 1)), "RESUME"
		)

	def test_submitted_pr_states(self):
		self.assertEqual(self.act(open_pr=open_pr(ci="pending")), "WAIT")
		self.assertEqual(self.act(open_pr=open_pr(ci="failure")), "FIX_CI")
		self.assertEqual(self.act(open_pr=open_pr(ci="missing")), "FIX_CI")
		self.assertEqual(self.act(open_pr=open_pr(ci="success", review="none")), "WAIT")
		self.assertEqual(self.act(open_pr=open_pr(ci="success", review="failure")), "ADDRESS_REVIEW")
		self.assertEqual(self.act(open_pr=open_pr(ci="success", review="success")), "WAIT")

	def test_no_new_task_starts_while_a_pr_is_open(self):
		result = s.decide_builder(s.State(tasks=TASKS, merged={"M0-T1"}, open_pr=open_pr(ci="pending")))
		self.assertEqual((result["action"], result["task"]), ("WAIT", "M1-T1"))

	def test_attempt_limit_stops_the_fix_loop(self):
		self.assertEqual(self.act(open_pr=open_pr(ci="failure", attempts=s.MAX_ATTEMPTS)), "STUCK")
		self.assertEqual(self.act(open_pr=open_pr(review="failure", attempts=s.MAX_ATTEMPTS)), "STUCK")
		self.assertEqual(self.act(open_pr=open_pr(ci="failure", attempts=s.MAX_ATTEMPTS - 1)), "FIX_CI")


class DecideReviewerTest(unittest.TestCase):
	def act(self, **kwargs):
		return s.decide_reviewer(s.State(tasks=TASKS, **kwargs))["action"]

	def test_reviews_only_submitted_green_unreviewed_prs(self):
		self.assertEqual(self.act(open_pr=open_pr()), "REVIEW")
		self.assertEqual(self.act(open_pr=open_pr(wip=True)), "NOTHING")
		self.assertEqual(self.act(open_pr=open_pr(ci="pending")), "NOTHING")
		self.assertEqual(self.act(open_pr=open_pr(ci="failure")), "NOTHING")
		self.assertEqual(self.act(), "NOTHING")

	def test_approved_but_unmerged_pr_is_merged(self):
		self.assertEqual(self.act(open_pr=open_pr(review="success")), "MERGE")

	def test_changes_requested_waits_for_builder(self):
		self.assertEqual(self.act(open_pr=open_pr(review="failure")), "NOTHING")

	def test_halt(self):
		self.assertEqual(self.act(halt_reason="x", open_pr=open_pr()), "HALT")


class HelpersTest(unittest.TestCase):
	def run_(self, status, conclusion=None, minutes=5, name=s.CI_WORKFLOW_NAME, event="pull_request"):
		return {
			"name": name,
			"event": event,
			"status": status,
			"conclusion": conclusion,
			"created_at": ago(minutes),
		}

	def test_ci_state(self):
		self.assertEqual(s.ci_state([], head_age_minutes=5), "pending")
		self.assertEqual(s.ci_state([], head_age_minutes=s.CI_MISSING_MINUTES + 1), "missing")
		self.assertEqual(s.ci_state([self.run_("in_progress")], 5), "pending")
		self.assertEqual(s.ci_state([self.run_("completed", "success")], 5), "success")
		self.assertEqual(s.ci_state([self.run_("completed", "failure")], 5), "failure")
		self.assertEqual(s.ci_state([self.run_("completed", "cancelled")], 5), "failure")

	def test_ci_state_uses_latest_run_and_ignores_other_workflows_and_events(self):
		runs = [self.run_("completed", "failure", minutes=30), self.run_("completed", "success", minutes=2)]
		self.assertEqual(s.ci_state(runs, 40), "success")
		self.assertEqual(s.ci_state([self.run_("completed", "success", name="Other")], 40), "missing")
		self.assertEqual(s.ci_state([self.run_("completed", "success", event="push")], 40), "missing")

	def status(self, state, minutes=1, login=OWNER, context=s.REVIEW_CONTEXT):
		return {"context": context, "state": state, "created_at": ago(minutes), "creator": {"login": login}}

	def test_review_state_trusts_only_the_owner_and_the_review_context(self):
		self.assertEqual(s.review_state([], OWNER), "none")
		self.assertEqual(s.review_state([self.status("success")], OWNER), "success")
		self.assertEqual(s.review_state([self.status("success", login="stranger")], OWNER), "none")
		self.assertEqual(s.review_state([self.status("success", context="other")], OWNER), "none")
		latest_wins = [self.status("success", minutes=20), self.status("failure", minutes=1)]
		self.assertEqual(s.review_state(latest_wins, OWNER), "failure")

	def comment(self, body, minutes, login=OWNER):
		return {"body": body, "created_at": ago(minutes), "user": {"login": login}}

	def test_count_attempts_resets_after_owner_retry_and_ignores_strangers(self):
		fail = s.REVIEW_MARKER.format(state="failure", sha="a" * 40)
		ok = s.REVIEW_MARKER.format(state="success", sha="a" * 40)
		comments = [self.comment(fail, 50), self.comment(ok, 40), self.comment(fail, 30, login="stranger")]
		runs = [{"created_at": ago(45)}, {"created_at": ago(10)}]
		self.assertEqual(s.count_attempts(runs, comments, OWNER), 3)
		comments.append(self.comment("/retry please", 20))
		self.assertEqual(s.count_attempts(runs, comments, OWNER), 1)
		comments.append(self.comment("/retry", 5, login="stranger"))
		self.assertEqual(s.count_attempts(runs, comments, OWNER), 1)

	def test_parse_repo(self):
		for url in (
			"https://github.com/o/r",
			"https://github.com/o/r.git",
			"git@github.com:o/r.git",
			"https://github.com/o/r/",
		):
			self.assertEqual(s.parse_repo(url), "o/r")
		with self.assertRaises(s.PipelineError):
			s.parse_repo("https://example.com/o/r")

	def test_task_from_branch_accepts_only_exact_task_branches(self):
		self.assertEqual(s.task_from_branch("task/M1-T2"), "M1-T2")
		for bad in ("task/M1-T2-extra", "feature/M1-T2", "task/x", "", None):
			self.assertIsNone(s.task_from_branch(bad))

	def test_task_brief_returns_only_the_requested_section(self):
		plan = "# Plan\n\n### M0-T1 — First\n\nalpha\n\n### M1-T1 — Second\n\nbeta\n"
		self.assertEqual(s.task_brief("M0-T1", plan), "### M0-T1 — First\n\nalpha")
		self.assertIn("beta", s.task_brief("M1-T1", plan))
		with self.assertRaises(s.PipelineError):
			s.task_brief("M9-T9", plan)

	def test_real_plan_has_a_brief_for_every_task_in_tasks_json(self):
		plan = s.PLAN_FILE.read_text(encoding="utf-8")
		tasks = s.load_tasks()
		self.assertGreater(len(tasks), 0)
		ids = [t["id"] for t in tasks]
		self.assertEqual(len(ids), len(set(ids)))
		for task in tasks:
			self.assertIn("Acceptance", s.task_brief(task["id"], plan))
			for dep in task["depends_on"]:
				self.assertLess(ids.index(dep), ids.index(task["id"]))


class FakeGitHub(s.GitHub):
	"""Answers GET requests from a table keyed by path; records writes."""

	def __init__(self, table):
		super().__init__(REPO, "token")
		self.table = table
		self.writes = []

	def request(self, method, path, body=None, params=None):
		if method != "GET":
			self.writes.append((method, path, body))
			return {"number": 1, "html_url": "u"}
		key = path.replace(f"/repos/{REPO}", "")
		for candidate, value in self.table.items():
			if key == candidate:
				return value(params or {}) if callable(value) else value
		raise AssertionError(f"unexpected GET {key} {params}")


def pull(number, branch, title, state="open", merged=False, login=OWNER, repo=REPO, updated=2):
	return {
		"number": number,
		"title": title,
		"state": state,
		"merged_at": ago(60) if merged else None,
		"user": {"login": login},
		"head": {"ref": branch, "sha": "b" * 40, "repo": {"full_name": repo}},
		"updated_at": ago(updated),
		"html_url": f"https://github.com/{REPO}/pull/{number}",
	}


class CollectStateTest(unittest.TestCase):
	def table(self, pulls, issues=(), runs=(), statuses=(), comments=(), head_age=3):
		return {
			"/issues": list(issues),
			"/pulls": list(pulls),
			f"/commits/{'b' * 40}": {"commit": {"committer": {"date": ago(head_age)}}},
			"/actions/runs": lambda params: {
				"workflow_runs": [] if params.get("status") == "failure" else list(runs)
			},
			f"/commits/{'b' * 40}/statuses": list(statuses),
			"/issues/9/comments": list(comments),
		}

	def test_merged_and_open_prs_are_derived_from_trusted_task_branches_only(self):
		pulls = [
			pull(9, "task/M1-T1", "[M1-T1] DocTypes"),
			pull(5, "task/M0-T1", "[M0-T1] Sandbox", state="closed", merged=True),
			pull(6, "task/M1-T2", "[M1-T2] Registry", state="closed", merged=True, login="stranger"),
			pull(7, "task/M1-T2", "[M1-T2] Registry", state="closed", merged=True, repo="fork/repo"),
			pull(8, "feature/x", "unrelated", state="closed", merged=True),
		]
		runs = [
			{
				"name": "CI",
				"event": "pull_request",
				"status": "completed",
				"conclusion": "success",
				"created_at": ago(2),
			}
		]
		state = s.collect_state(FakeGitHub(self.table(pulls, runs=runs)), TASKS, now=NOW)
		self.assertEqual(state.merged, {"M0-T1"})
		self.assertEqual(
			(state.open_pr.number, state.open_pr.task, state.open_pr.ci, state.open_pr.review),
			(9, "M1-T1", "success", "none"),
		)
		self.assertFalse(state.open_pr.wip)

	def test_wip_and_idle_time_use_the_most_recent_activity(self):
		pulls = [pull(9, "task/M1-T1", "WIP: [M1-T1] DocTypes", updated=4)]
		state = s.collect_state(FakeGitHub(self.table(pulls, head_age=90)), TASKS, now=NOW)
		self.assertTrue(state.open_pr.wip)
		self.assertAlmostEqual(state.open_pr.idle_minutes, 4, delta=0.1)

	def test_halt_issue_must_be_an_issue_with_the_prefix(self):
		issues = [
			{"number": 3, "title": "[pipeline-halt] stop"},
			{"number": 4, "title": "[pipeline-halt] pr", "pull_request": {}},
		]
		state = s.collect_state(FakeGitHub(self.table([], issues=issues)), TASKS, now=NOW)
		self.assertIn("#3", state.halt_reason)
		state = s.collect_state(FakeGitHub(self.table([], issues=issues[1:])), TASKS, now=NOW)
		self.assertIsNone(state.halt_reason)


class MergeGuardTest(unittest.TestCase):
	def gh(self, review_state, ci_conclusion="success", title="[M1-T1] DocTypes"):
		runs = [
			{
				"name": "CI",
				"event": "pull_request",
				"status": "completed",
				"conclusion": ci_conclusion,
				"created_at": ago(2),
			}
		]
		statuses = (
			[]
			if review_state is None
			else [
				{
					"context": s.REVIEW_CONTEXT,
					"state": review_state,
					"created_at": ago(1),
					"creator": {"login": OWNER},
				}
			]
		)
		table = CollectStateTest().table([pull(9, "task/M1-T1", title)], runs=runs, statuses=statuses)
		table["/pulls/9"] = pull(9, "task/M1-T1", title)
		return FakeGitHub(table)

	def args(self, sha="b" * 40):
		return types.SimpleNamespace(pr=9, sha=sha)

	def test_merges_only_when_green_and_approved_at_the_head_commit(self):
		gh = self.gh("success")
		s.cmd_merge(gh, TASKS, self.args())
		self.assertEqual(gh.writes[0][:2], ("PUT", f"/repos/{REPO}/pulls/9/merge"))
		self.assertEqual(gh.writes[0][2]["sha"], "b" * 40)

	def test_refuses_without_approval_failed_ci_wip_or_moved_head(self):
		for gh in (
			self.gh(None),
			self.gh("failure"),
			self.gh("success", ci_conclusion="failure"),
			self.gh("success", title="WIP: [M1-T1] DocTypes"),
		):
			with self.assertRaises(s.PipelineError):
				s.cmd_merge(gh, TASKS, self.args())
			self.assertEqual(gh.writes, [])
		gh = self.gh("success")
		with self.assertRaises(s.PipelineError):
			s.cmd_merge(gh, TASKS, self.args(sha="c" * 40))
		self.assertEqual(gh.writes, [])


class TransportTest(unittest.TestCase):
	def test_token_travels_on_stdin_not_in_argv_and_errors_are_raised(self):
		calls = {}

		def runner(cmd, input, capture_output, text):
			calls["cmd"], calls["input"] = cmd, input
			return types.SimpleNamespace(returncode=0, stdout='{"message": "Not Found"}\n404', stderr="")

		gh = s.GitHub(REPO, "secret-token", runner=runner)
		with self.assertRaises(s.PipelineError) as ctx:
			gh.get("/pulls/1")
		self.assertIn("404", str(ctx.exception))
		self.assertNotIn("secret-token", " ".join(calls["cmd"]))
		self.assertIn("Authorization: Bearer secret-token", calls["input"])

	def test_success_body_is_parsed(self):
		def runner(*args, **kwargs):
			return types.SimpleNamespace(returncode=0, stdout='{"ok": true}\n200', stderr="")

		self.assertEqual(s.GitHub(REPO, "t", runner=runner).get("/x"), {"ok": True})


if __name__ == "__main__":
	unittest.main()
