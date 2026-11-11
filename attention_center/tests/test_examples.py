"""The sample consumer app of examples/ (docs/PROVIDER_CONTRACT.md), run on the site as if it were installed."""

import ast
import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from attention_center import api
from attention_center.engine import realtime, registry, runner
from attention_center.tests.test_registry import make_user_group
from attention_center.tests.utils import make_desk_role, make_user

SOURCE = "Attention Source"
EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
APP = "sample_app"
MY_REQUESTS = "sample_app.my_requests"
TEAM_QUEUE = "sample_app.team_queue"
# The DocType the sample app would ship, which its sources read. Created in setUpClass and dropped in
# tearDownClass: DocType changes commit, so a test cannot roll them back.
REQUEST = "Sample Request"
AGENT = "_Test Sample Agent"
OUTSIDER = "_Test Sample Outsider"


def create_request_doctype() -> None:
	for role in (AGENT, OUTSIDER):
		if not frappe.db.exists("Role", role):
			make_desk_role(role)
	if frappe.db.exists("DocType", REQUEST):
		frappe.delete_doc("DocType", REQUEST, force=True)
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": REQUEST,
			"module": "Custom",
			"custom": 1,
			"fields": [
				{"fieldname": "subject", "fieldtype": "Data", "label": "Subject"},
				{
					"fieldname": "status",
					"fieldtype": "Select",
					"options": "Open\nClosed",
					"default": "Open",
					"label": "Status",
				},
				{
					"fieldname": "priority",
					"fieldtype": "Select",
					"options": "Low\nMedium\nHigh\nCritical",
					"default": "Medium",
					"label": "Priority",
				},
				{"fieldname": "due_date", "fieldtype": "Date", "label": "Due Date"},
				{"fieldname": "team", "fieldtype": "Link", "options": "User Group", "label": "Team"},
				{"fieldname": "assigned_to", "fieldtype": "Link", "options": "User", "label": "Assigned To"},
			],
			"permissions": [{"role": AGENT, "read": 1, "write": 1, "create": 1}],
		}
	).insert()


def add_request(subject: str, **values) -> str:
	return (
		frappe.get_doc({"doctype": REQUEST, "subject": subject, **values})
		.insert(ignore_permissions=True)
		.name
	)


class TestSampleApp(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_request_doctype()
		frappe.db.commit()
		sys.path.append(str(EXAMPLES))

	@classmethod
	def tearDownClass(cls):
		sys.path.remove(str(EXAMPLES))
		frappe.db.rollback()
		frappe.delete_doc("DocType", REQUEST, force=True)
		# Frappe keeps the table of a deleted DocType; this test's table goes with it.
		frappe.db.sql_ddl(f"drop table if exists `tab{REQUEST}`")
		for role in (AGENT, OUTSIDER):
			frappe.delete_doc("Role", role, force=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		# The sample app is importable from examples/ and listed among the site's apps, so Frappe reads its
		# hooks.py and resolves its dotted paths as it would for an installed app.
		installed_apps = frappe.get_installed_apps
		for patcher in (
			patch("frappe.get_installed_apps", side_effect=lambda **kwargs: [*installed_apps(**kwargs), APP]),
			patch("frappe.publish_realtime"),
		):
			patcher.start()
			self.addCleanup(patcher.stop)
		registry.sync_sources()

		self.agent = make_user("sample.agent@example.com", [AGENT])
		self.colleague = make_user("sample.colleague@example.com", [AGENT])
		self.outsider = make_user("sample.outsider@example.com", [OUTSIDER])
		self.team = make_user_group("_Test Sample Team", [self.agent, self.outsider])
		self.other_team = make_user_group("_Test Sample Other Team", [self.colleague])
		self.yesterday = add_days(today(), -1)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		registry.clear_visibility_cache()
		for key in (MY_REQUESTS, TEAM_QUEUE):
			frappe.cache.delete_value(runner.COUNT_CACHE.format(key))

	def summary(self, user: str) -> dict[str, dict]:
		"""The user's summary entries by source key, counted afresh."""
		for key in (MY_REQUESTS, TEAM_QUEUE):
			frappe.cache.delete_value(runner.COUNT_CACHE.format(key))
		frappe.set_user(user)
		try:
			return {source["key"]: source for source in api.get_summary()["sources"]}
		finally:
			frappe.set_user("Administrator")

	def counts(self, user: str, key: str) -> dict:
		entry = self.summary(user)[key]
		self.assertEqual(entry["state"], "ok")
		return {name: entry[name] for name in ("count", "urgent", "immediate", "overdue")}

	def items(self, user: str, key: str) -> list[dict]:
		frappe.set_user(user)
		try:
			result = api.get_items(key)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(result["state"], "ok")
		return result["items"]

	def item_ids(self, user: str, key: str) -> list[str]:
		return [item["id"] for item in self.items(user, key)]

	def nudged(self) -> dict[str | None, list[str]]:
		"""Commit's nudges: the source keys each user (None for the whole site) was told to refresh."""
		frappe.publish_realtime.reset_mock()
		frappe.db.after_commit.run()
		return {
			call.kwargs.get("user"): sorted(call.args[1]["sources"])
			for call in frappe.publish_realtime.call_args_list
			if call.args[:1] == (realtime.EVENT,)
		}

	def test_the_hook_entries_become_system_sources_of_the_sample_app(self):
		self.assertEqual(
			frappe.db.get_value(SOURCE, MY_REQUESTS, ["app", "is_system", "enabled", "source_type", "kind"]),
			(APP, 1, 1, "DocType Query", "Action"),
		)
		self.assertEqual(
			frappe.db.get_value(SOURCE, TEAM_QUEUE, ["app", "is_system", "enabled", "source_type", "kind"]),
			(APP, 1, 1, "Python", "Action"),
		)

	def test_my_requests_holds_the_open_requests_assigned_to_the_user(self):
		late = add_request(
			"Replace the door badge reader", assigned_to=self.agent, priority="High", due_date=self.yesterday
		)
		critical = add_request("Server room is too warm", assigned_to=self.agent, priority="Critical")
		routine = add_request("Order printer paper", assigned_to=self.agent)
		add_request("Archive last year's files", assigned_to=self.agent, status="Closed")
		colleagues = add_request("Book a meeting room", assigned_to=self.colleague)

		self.assertEqual(
			self.counts(self.agent, MY_REQUESTS), {"count": 3, "urgent": 1, "immediate": 1, "overdue": 1}
		)
		self.assertEqual(self.item_ids(self.agent, MY_REQUESTS), [late, critical, routine])
		self.assertEqual(self.item_ids(self.colleague, MY_REQUESTS), [colleagues])

	def test_team_queue_holds_the_unassigned_open_requests_of_the_users_teams(self):
		late = add_request("Replace the door badge reader", team=self.team, due_date=self.yesterday)
		critical = add_request("Server room is too warm", team=self.team, priority="Critical")
		add_request("Order printer paper", team=self.team, assigned_to=self.colleague)
		add_request("Archive last year's files", team=self.team, status="Closed")
		other_team = add_request("Book a meeting room", team=self.other_team)
		add_request("Water the plants")

		self.assertEqual(
			self.counts(self.agent, TEAM_QUEUE), {"count": 2, "urgent": 0, "immediate": 1, "overdue": 1}
		)
		items = self.items(self.agent, TEAM_QUEUE)
		self.assertEqual([item["id"] for item in items], [late, critical])
		self.assertEqual(
			{name: items[0][name] for name in ("title", "route", "type_label", "from_label", "status_label")},
			{
				"title": "Replace the door badge reader",
				"route": f"/app/sample-request/{late}",
				"type_label": self.team,
				"from_label": "Administrator",
				"status_label": "Unassigned",
			},
		)
		self.assertEqual((items[0]["due"], items[0]["overdue"]), (self.yesterday, True))
		self.assertEqual(self.item_ids(self.colleague, TEAM_QUEUE), [other_team])

	def test_team_queue_counts_what_arrived_since_the_user_last_looked(self):
		add_request("Replace the door badge reader", team=self.team)
		self.assertEqual(self.summary(self.agent)[TEAM_QUEUE]["new_since"], 1)

		frappe.set_user(self.agent)
		api.mark_seen(TEAM_QUEUE)
		frappe.set_user("Administrator")
		newest = add_request("Order printer paper", team=self.team)

		entry = self.summary(self.agent)[TEAM_QUEUE]
		self.assertEqual((entry["count"], entry["new_since"]), (2, 1))
		self.assertEqual(
			entry["latest"], frappe.db.get_value(REQUEST, newest, "creation").isoformat(timespec="seconds")
		)

	def test_a_user_who_cannot_read_requests_sees_none_of_them(self):
		add_request("Replace the door badge reader", assigned_to=self.outsider)
		queued = add_request("Server room is too warm", team=self.team)

		summary = self.summary(self.outsider)
		self.assertNotIn(MY_REQUESTS, summary)
		self.assertEqual((summary[TEAM_QUEUE]["state"], summary[TEAM_QUEUE]["count"]), ("ok", 0))
		self.assertEqual(self.items(self.outsider, TEAM_QUEUE), [])
		frappe.set_user(self.outsider)
		self.assertRaises(frappe.PermissionError, api.get_items, MY_REQUESTS)
		frappe.set_user("Administrator")
		self.assertEqual(
			self.item_ids(self.agent, TEAM_QUEUE), [queued], "the agent of the same team sees it"
		)

	def test_saving_a_request_nudges_its_assignee_and_the_members_of_its_teams(self):
		request = frappe.get_doc(
			{
				"doctype": REQUEST,
				"subject": "Server room is too warm",
				"team": self.team,
				"assigned_to": self.agent,
			}
		).insert(ignore_permissions=True)
		self.assertEqual(self.nudged(), {self.agent: [MY_REQUESTS, TEAM_QUEUE], self.outsider: [TEAM_QUEUE]})

		request.update({"team": self.other_team, "assigned_to": None})
		request.save(ignore_permissions=True)
		self.assertEqual(
			self.nudged(),
			{
				self.agent: [MY_REQUESTS, TEAM_QUEUE],
				self.outsider: [TEAM_QUEUE],
				self.colleague: [TEAM_QUEUE],
			},
		)

	def test_the_sample_app_nudges_only_on_a_site_with_attention_center(self):
		attention = importlib.import_module("sample_app.attention")

		with patch("frappe.get_installed_apps", return_value=["frappe", APP]):
			attention.nudge_attention_center([self.agent], TEAM_QUEUE)
		self.assertEqual(self.nudged(), {})

		attention.nudge_attention_center([self.agent], TEAM_QUEUE)
		self.assertEqual(self.nudged(), {self.agent: [TEAM_QUEUE]})


class TestSampleAppImports(FrappeTestCase):
	def test_the_sample_app_never_imports_attention_center(self):
		paths = sorted((EXAMPLES / APP).rglob("*.py"))
		self.assertEqual([path.name for path in paths], ["__init__.py", "attention.py", "hooks.py"])
		for path in paths:
			tree = ast.parse(path.read_text(), filename=str(path))
			modules = {
				alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
			}
			modules |= {
				node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
			}
			with self.subTest(path.name):
				self.assertEqual(
					{module for module in modules if module.split(".")[0] == "attention_center"}, set()
				)
