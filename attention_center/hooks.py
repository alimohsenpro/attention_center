app_name = "attention_center"
app_title = "Attention Center"
app_publisher = "Attention Center Contributors"
app_description = "Unified attention center for Frappe: what needs you now, across every app"
app_email = "maintainers@example.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "attention_center",
# 		"logo": "/assets/attention_center/logo.png",
# 		"title": "Attention Center",
# 		"route": "/attention_center",
# 		"has_permission": "attention_center.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/attention_center/css/attention_center.css"
# app_include_js = "/assets/attention_center/js/attention_center.js"

# include js, css files in header of web template
# web_include_css = "/assets/attention_center/css/attention_center.css"
# web_include_js = "/assets/attention_center/js/attention_center.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "attention_center/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "attention_center/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "attention_center.utils.jinja_methods",
# 	"filters": "attention_center.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "attention_center.install.before_install"
after_install = "attention_center.install.after_install"
after_migrate = "attention_center.install.after_migrate"

fixtures = [{"dt": "Role", "filters": [["name", "=", "Attention Manager"]]}]

# Desk Boot
# ---------

extend_bootinfo = "attention_center.boot.extend_bootinfo"

# Attention Sources
# -----------------
# The built-in sources, declared through the same hook as any consumer app's

from attention_center.sources.builtin import SOURCES as attention_sources

# Uninstallation
# ------------

# before_uninstall = "attention_center.uninstall.before_uninstall"
# after_uninstall = "attention_center.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "attention_center.utils.before_app_install"
# after_app_install = "attention_center.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "attention_center.utils.before_app_uninstall"
# after_app_uninstall = "attention_center.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "attention_center.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Nudge the users a change concerns (on_change also follows insert, submit, cancel and db_set)

doc_events = {
	"*": {
		"on_change": "attention_center.engine.realtime.on_doc_event",
		"on_trash": "attention_center.engine.realtime.on_doc_event",
	}
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"attention_center.tasks.all"
# 	],
# 	"daily": [
# 		"attention_center.tasks.daily"
# 	],
# 	"hourly": [
# 		"attention_center.tasks.hourly"
# 	],
# 	"weekly": [
# 		"attention_center.tasks.weekly"
# 	],
# 	"monthly": [
# 		"attention_center.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "attention_center.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "attention_center.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "attention_center.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["attention_center.utils.before_request"]
# after_request = ["attention_center.utils.after_request"]

# Job Events
# ----------
# before_job = ["attention_center.utils.before_job"]
# after_job = ["attention_center.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"attention_center.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
