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
