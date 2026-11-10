const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

// Text for HTML markup: every character that could open a tag, an entity or an attribute is escaped.
export function escapeHtml(value) {
	return String(value ?? "").replace(/[&<>"']/g, (character) => ENTITIES[character]);
}
