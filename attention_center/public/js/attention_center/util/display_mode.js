// The window's display modes [FR-UI-03], named as in the display_mode preference (§5). No DOM and no frappe,
// so they can be tested with node --test.
const MODES = ["Dialog", "Panel", "Drawer"];

// The mode of the window for the effective display_mode preference. A value that names no mode (a default
// cleared through the API) gets the default dialog, so the window always has a container.
export function displayMode(preference) {
	return MODES.includes(preference) ? preference : "Dialog";
}

// The mode the window's mode button switches to: dialog, then panel, then drawer, then dialog again.
export function nextDisplayMode(preference) {
	return MODES[(MODES.indexOf(displayMode(preference)) + 1) % MODES.length];
}
