"""The sources this app declares in its own hooks, as plain data like any consumer app's (§4.5)."""

APPROVALS = {
	"key": "attention_center.approvals",
	"contract_version": 1,
	"label": "Approvals",
	"kind": "action",
	"type": "python",
	"get_count": "attention_center.sources.approvals.get_count",
	"get_items": "attention_center.sources.approvals.get_items",
	"list_route": "/app/workflow-action?status=Open",
}

ASSIGNMENTS = {
	"key": "attention_center.assignments",
	"contract_version": 1,
	"label": "Assignments",
	"kind": "action",
	"type": "doctype_query",
	"doctype": "ToDo",
	"filters": [["status", "=", "Open"], ["allocated_to", "=", "{user}"]],
	"fields": {
		"title": "description",
		"from": "assigned_by",
		"date": "creation",
		"priority": "priority",
		"due": "date",
	},
	"priority_map": {"High": "urgent"},
	"recipient_fields": ["allocated_to"],
	"route_fields": {"doctype": "reference_type", "name": "reference_name"},
	"list_route": "/app/todo?status=Open",
}

NOTIFICATIONS = {
	"key": "attention_center.notifications",
	"contract_version": 1,
	"label": "Notifications",
	"kind": "info",
	"type": "doctype_query",
	"doctype": "Notification Log",
	"filters": [["for_user", "=", "{user}"], ["read", "=", 0]],
	"fields": {"title": "subject", "from": "from_user", "date": "creation"},
	"recipient_fields": ["for_user"],
	"route_fields": {"route": "link", "doctype": "document_type", "name": "document_name"},
	"list_route": "/app/notification-log?read=0",
}

SOURCES = [APPROVALS, ASSIGNMENTS, NOTIFICATIONS]
