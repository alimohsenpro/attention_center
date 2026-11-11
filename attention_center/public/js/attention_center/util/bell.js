// The notification bell of Frappe 15's stock navbar (frappe/public/js/frappe/ui/toolbar/navbar.html). A desk whose
// navbar differs (a theme, Frappe 16) does not match it and keeps its bell: the setting is CSS only (D-14).
export const STANDARD_BELL_CSS = ".navbar .dropdown-notifications { display: none !important; }";

// Hides the stock bell with a <style> in the page's head, the only style this app puts outside its shadow root, and
// returns the function that shows the bell again.
export function hideStandardBell(doc) {
	const style = doc.createElement("style");
	style.textContent = STANDARD_BELL_CSS;
	doc.head.append(style);
	return () => style.remove();
}
