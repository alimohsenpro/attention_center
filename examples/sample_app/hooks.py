# The part of the sample app's hooks.py that plugs it into Attention Center (docs/PROVIDER_CONTRACT.md).
# Plain data and no import of attention_center: on a site without Attention Center, Frappe ignores it.

attention_sources = [
	{
		# Declarative: the open requests assigned to the user, read with the user's permissions.
		"key": "sample_app.my_requests",
		"contract_version": 1,
		"label": "My Requests",
		"kind": "action",
		"type": "doctype_query",
		"doctype": "Sample Request",
		"filters": [["status", "=", "Open"], ["assigned_to", "=", "{user}"]],
		"fields": {
			"title": "subject",
			"from": "owner",
			"date": "creation",
			"priority": "priority",
			"due": "due_date",
			"status": "status",
		},
		"priority_map": {"High": "urgent", "Critical": "immediate"},
		"recipient_fields": ["assigned_to"],
		"list_route": "/app/sample-request?status=Open",
	},
	{
		# Python: the unassigned open requests of the user's teams. "The user's teams" is a lookup that a
		# list of filters cannot express, so the app computes the list itself (sample_app/attention.py).
		"key": "sample_app.team_queue",
		"contract_version": 1,
		"label": "Team Queue",
		"kind": "action",
		"type": "python",
		"get_count": "sample_app.attention.team_queue_count",
		"get_items": "sample_app.attention.team_queue_items",
		"get_recipients": "sample_app.attention.team_queue_recipients",
		"watch_doctypes": ["Sample Request"],
		"list_route": "/app/sample-request?status=Open",
	},
]
