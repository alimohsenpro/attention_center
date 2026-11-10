const UNSAFE = /[\u0000-\u0020\u007f\\]/;
const BASE = "http://desk.invalid";

// Only desk routes are opened (§7.2, §8). The resolved path is checked too, because dot segments such as
// "/app/../" or "/app/%2e%2e/" lead out of /app/.
export function isDeskRoute(route) {
	return (
		typeof route === "string" &&
		route.startsWith("/app/") &&
		!UNSAFE.test(route) &&
		new URL(route, BASE).pathname.startsWith("/app/")
	);
}

// The argument of frappe.set_route for a desk route: the decoded path segments after /app/, then the query as
// an object of route options. Given the route as text, frappe.set_route would encode its "?" into the last
// segment (make_url in frappe/public/js/frappe/router.js).
export function routeArguments(route) {
	const url = new URL(route, BASE);
	const segments = url.pathname.split("/").slice(2).filter(Boolean).map(decodeSegment);
	const options = Object.fromEntries(url.searchParams);
	return segments.length && Object.keys(options).length ? [...segments, options] : segments;
}

// As Frappe's router does: a segment that is not valid percent-encoding is kept as it is.
function decodeSegment(segment) {
	try {
		return decodeURIComponent(segment);
	} catch {
		return segment;
	}
}
