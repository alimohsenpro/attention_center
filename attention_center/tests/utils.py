import frappe


def make_user(email: str, roles: list[str]) -> str:
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@", 1)[0],
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in roles],
		}
	).insert(ignore_permissions=True)
	return email


def make_desk_role(role: str) -> str:
	frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
	return role
