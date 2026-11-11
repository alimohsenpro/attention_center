"""Smoke tests of the desk client in Chromium [FR-UI-09, FR-UI-10, NFR-A11Y-01]: the launcher and the window in
English (left to right) and Arabic (right to left), in the light and the dark desk theme, opened and closed with
the keyboard, the three display modes, the sticky toast of an immediate announcement published before the page
loaded, which an acknowledgement stops [FR-ANN-02], and "Remind me later" on an item [FR-SNZ-01].

scripts/ci/run_tests.sh runs them with python3 after the backend tests. They are skipped, with the reason, when
Playwright for Python or its Chromium is missing. Otherwise they build the app's assets, complete the site's setup
wizard with Frappe's own test values if nobody did, serve the site with `bench serve` on a free port, and create
one desk user with an assignment and a notification, deleted again at the end. Set AC_UI_SCREENSHOTS to a directory to keep a
screenshot of each open window.
"""

import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

try:
	from playwright.sync_api import Error as PlaywrightError
	from playwright.sync_api import expect, sync_playwright
except ImportError:
	sync_playwright = None

BENCH_DIR = Path(os.environ.get("BENCH_DIR", Path.home() / "frappe-bench"))
SITE = os.environ.get("SITE", "test_site")
# The Administrator password scripts/dev/bench_up.sh and scripts/ci/install.sh give the site.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
SCREENSHOTS = os.environ.get("AC_UI_SCREENSHOTS")

SUFFIX = secrets.token_hex(4)
USER = f"ac-ui-{SUFFIX}@example.com"
PASSWORD = secrets.token_urlsafe(18)
ROLE = f"Attention UI Smoke {SUFFIX}"
ITEM = "Check the sample request"
ANNOUNCEMENT = "The sample office closes early today"
ANNOUNCEMENT_TO_ACKNOWLEDGE = "Read the sample safety note"
TEXTS = {
	"en": {"launcher": "Attention Center", "title": "What needs your attention", "open": "Open"},
	"ar": {"launcher": "مركز الانتباه", "title": "ما يحتاج انتباهك", "open": "فتح"},
}
# --ac-surface of each theme (docs/DESIGN_TOKENS.md).
SURFACES = {"light": "rgb(255, 255, 255)", "dark": "rgb(24, 32, 31)"}
# The launcher's and the panel's distance from the edges of the page.
EDGE = 16

state = {}


def setUpModule():
	if sync_playwright is None:
		raise unittest.SkipTest(
			"Playwright for Python is not installed (pip install playwright; playwright install chromium)"
		)
	playwright = sync_playwright().start()
	unittest.addModuleCleanup(playwright.stop)
	try:
		browser = playwright.chromium.launch()
	except PlaywrightError as error:
		raise unittest.SkipTest(f"Chromium for Playwright is not available: {str(error).splitlines()[0]}")
	unittest.addModuleCleanup(browser.close)
	expect.set_options(timeout=15_000)

	# The tests check the code as it is now, not the last build.
	bench("build", "--app", "attention_center")
	if not (BENCH_DIR / "sites" / "assets" / "frappe" / "dist").is_dir():
		bench("build", "--app", "frappe")
	# Until the setup wizard is complete, the desk shows nothing else.
	bench("--site", SITE, "execute", "frappe.utils.install.complete_setup_wizard")
	# Translations and the bundles' file names are cached.
	bench("--site", SITE, "clear-cache")

	base_url = f"http://127.0.0.1:{serve()}"
	admin = playwright.request.new_context(base_url=base_url)
	unittest.addModuleCleanup(admin.dispose)
	login(admin, "Administrator", ADMIN_PASSWORD)
	state.update(playwright=playwright, browser=browser, admin=admin, base_url=base_url)
	create_user_with_items()


def bench(*args: str) -> None:
	result = subprocess.run(["bench", *args], cwd=BENCH_DIR, capture_output=True, text=True)
	if result.returncode:
		raise RuntimeError(f"bench {' '.join(args)} failed:\n{(result.stdout + result.stderr)[-2000:]}")


def serve() -> int:
	with socket.socket() as probe:
		probe.bind(("127.0.0.1", 0))
		port = probe.getsockname()[1]
	log = tempfile.TemporaryFile()
	server = subprocess.Popen(
		["bench", "--site", SITE, "serve", "--port", str(port), "--noreload"],
		cwd=BENCH_DIR,
		stdout=log,
		stderr=subprocess.STDOUT,
	)
	unittest.addModuleCleanup(log.close)
	unittest.addModuleCleanup(stop, server)
	deadline = time.monotonic() + 60
	while time.monotonic() < deadline:
		try:
			urllib.request.urlopen(f"http://127.0.0.1:{port}/api/method/ping", timeout=2)
			return port
		except OSError:
			if server.poll() is not None:
				break
			time.sleep(0.5)
	log.seek(0)
	raise RuntimeError(f"bench serve did not answer:\n{log.read().decode(errors='replace')[-2000:]}")


def stop(server: subprocess.Popen) -> None:
	server.terminate()
	server.wait(timeout=10)


def login(context, user: str, password: str) -> None:
	response = context.post("/api/method/login", form={"usr": user, "pwd": password})
	if not response.ok:
		raise RuntimeError(f"{user} could not log in: HTTP {response.status}")


def announce(test: unittest.TestCase, title: str, requires_acknowledgement: int) -> None:
	"""An immediate announcement for the user's role, deleted with its receipts when the test ends."""
	announcement = call(
		"POST",
		"/api/resource/Attention Announcement",
		{
			"title": title,
			"priority": "Immediate",
			"requires_acknowledgement": requires_acknowledgement,
			"published": 1,
			"all_users": 0,
			"roles": [{"role": ROLE}],
		},
	)
	test.addCleanup(call, "DELETE", f"/api/resource/Attention Announcement/{announcement['name']}")
	# Cleanups run last in, first out: the receipts go before the announcement they link to.
	test.addCleanup(delete_receipts, announcement["name"])


def delete_receipts(announcement: str) -> None:
	receipts = state["admin"].get(
		"/api/resource/Attention Announcement Receipt",
		params={"filters": json.dumps([["announcement", "=", announcement]])},
	)
	for receipt in receipts.json()["data"]:
		call("DELETE", f"/api/resource/Attention Announcement Receipt/{receipt['name']}")


def call(method: str, path: str, data: dict | None = None, missing_ok: bool = False) -> dict | None:
	response = state["admin"].fetch(path, method=method, data=data)
	if missing_ok and response.status == 404:
		return None
	if not response.ok:
		raise RuntimeError(f"{method} {path}: HTTP {response.status} {response.text()[:500]}")
	return response.json().get("data")


def create_user_with_items() -> None:
	call("POST", "/api/resource/Role", {"role_name": ROLE, "desk_access": 1})
	unittest.addModuleCleanup(call, "DELETE", f"/api/resource/Role/{ROLE}")
	call(
		"POST",
		"/api/resource/User",
		{
			"email": USER,
			"first_name": "Sample",
			"send_welcome_email": 0,
			"new_password": PASSWORD,
			"roles": [{"role": ROLE}],
		},
	)
	unittest.addModuleCleanup(call, "DELETE", f"/api/resource/User/{USER}")
	# The user's preferences link to the user.
	unittest.addModuleCleanup(
		call, "DELETE", f"/api/resource/Attention User Preference/{USER}", missing_ok=True
	)
	todo = call(
		"POST",
		"/api/resource/ToDo",
		{"description": ITEM, "allocated_to": USER, "priority": "High", "status": "Open"},
	)
	unittest.addModuleCleanup(call, "DELETE", f"/api/resource/ToDo/{todo['name']}")
	state["todo"] = todo["name"]
	notification = call(
		"POST",
		"/api/resource/Notification Log",
		{"for_user": USER, "subject": "A sample notice", "type": "Alert"},
	)
	unittest.addModuleCleanup(call, "DELETE", f"/api/resource/Notification Log/{notification['name']}")

	# The window would open by itself after every login, since the user has an action item [FR-ALERT-05].
	user = state["playwright"].request.new_context(base_url=state["base_url"])
	login(user, USER, PASSWORD)
	response = user.post(
		"/api/method/attention_center.api.set_preferences", data={"prefs": {"auto_open_on_login": "No"}}
	)
	if not response.ok:
		raise RuntimeError(f"set_preferences: HTTP {response.status} {response.text()[:500]}")
	user.dispose()


class TestDeskClient(unittest.TestCase):
	def open_desk(self, lang: str, theme: str):
		"""A desk page of the user in a fresh browser, and the client's errors on the console."""
		call("PUT", f"/api/resource/User/{USER}", {"language": lang, "desk_theme": theme.title()})
		# Without motion the window takes its place at once, so that its position can be measured.
		context = state["browser"].new_context(
			base_url=state["base_url"], viewport={"width": 1280, "height": 800}, reduced_motion="reduce"
		)
		self.addCleanup(context.close)
		login(context.request, USER, PASSWORD)
		page = context.new_page()
		errors = []
		page.on("console", lambda message: message.type == "error" and errors.append(message.text))
		page.goto("/app/todo")
		return page, errors

	def test_launcher_and_window_in_each_language_and_theme(self):
		for lang, theme in (("en", "light"), ("en", "dark"), ("ar", "light"), ("ar", "dark")):
			with self.subTest(lang=lang, theme=theme):
				page, errors = self.open_desk(lang, theme)
				rtl = lang == "ar"
				host = page.locator("#attention-center-root")
				expect(host).to_have_attribute("dir", "rtl" if rtl else "ltr")
				expect(host).to_have_attribute("data-theme", theme)

				launcher = page.locator(".launcher-main")
				expect(launcher.locator(".launcher-count")).to_have_text("1")
				expect(launcher.locator(".launcher-label")).to_have_text(TEXTS[lang]["launcher"])
				expect(launcher.locator(".launcher-dot")).to_be_visible()
				# The bottom inline-end corner: bottom right in English, bottom left in Arabic [FR-UI-01].
				left, right, bottom = edges(page, launcher)
				self.assertAlmostEqual(left if rtl else right, EDGE, delta=1)
				self.assertAlmostEqual(bottom, EDGE, delta=1)

				launcher.click()
				window = page.locator(".window")
				expect(window).to_be_visible()
				expect(page.locator(".frame")).to_have_attribute("data-mode", "dialog")
				expect(page.locator(".window-title")).to_have_text(TEXTS[lang]["title"])
				expect(page.locator("tbody tr").first).to_contain_text(ITEM)
				expect(page.locator(".open-link").first).to_have_text(TEXTS[lang]["open"])
				self.assertEqual(
					window.evaluate("node => getComputedStyle(node).backgroundColor"), SURFACES[theme]
				)
				# The title starts the header and the actions end it, on the side the language reads from.
				title = page.locator(".window-title").bounding_box()
				actions = page.locator(".window-actions").bounding_box()
				self.assertEqual(title["x"] > actions["x"], rtl)
				if SCREENSHOTS:
					page.screenshot(path=os.path.join(SCREENSHOTS, f"window-{lang}-{theme}.png"))

				# Esc closes and gives focus back to the launcher; the shortcut opens and closes [FR-UI-08].
				page.keyboard.press("Escape")
				expect(window).to_be_hidden()
				self.assertEqual(
					host.evaluate("node => node.shadowRoot.activeElement?.className"), "launcher-main"
				)
				page.keyboard.press("Alt+Shift+A")
				expect(window).to_be_visible()
				page.keyboard.press("Alt+Shift+A")
				expect(window).to_be_hidden()
				self.assertEqual([error for error in errors if "[attention_center]" in error], [])

	def test_the_three_display_modes_right_to_left(self):
		page, errors = self.open_desk("ar", "light")
		page.locator(".launcher-main").click()
		window = page.locator(".window")
		expect(window).to_be_visible()
		mode = page.locator(".mode-button")

		mode.click()
		expect(page.locator(".frame")).to_have_attribute("data-mode", "panel")
		expect(window).to_contain_text(ITEM)
		# Above the launcher, at the inline end: the left in Arabic.
		left, _right, bottom = edges(page, window)
		self.assertAlmostEqual(left, EDGE, delta=1)
		self.assertGreater(bottom, EDGE + 44)

		mode.click()
		expect(page.locator(".frame")).to_have_attribute("data-mode", "drawer")
		expect(window).to_contain_text(ITEM)
		left, _right, bottom = edges(page, window)
		self.assertAlmostEqual(left, 0, delta=1)
		self.assertAlmostEqual(bottom, 0, delta=1)

		mode.click()
		expect(page.locator(".frame")).to_have_attribute("data-mode", "dialog")
		expect(window).to_contain_text(ITEM)
		self.assertEqual([error for error in errors if "[attention_center]" in error], [])

	def test_an_acknowledged_immediate_announcement_is_not_raised_again(self):
		"""Acknowledged from "All", it raises no toast at the next page load and leaves no dot [FR-ANN-02, FR-ANN-03]."""
		announce(self, ANNOUNCEMENT_TO_ACKNOWLEDGE, requires_acknowledgement=1)
		page, errors = self.open_desk("en", "light")
		toast = page.locator(".toast[data-level='immediate']")
		expect(toast).to_contain_text("New item in Announcements")

		page.locator(".launcher-main").click()
		expect(page.locator(".tab[aria-selected='true']")).to_contain_text("All")
		page.locator("tbody tr", has_text=ANNOUNCEMENT_TO_ACKNOWLEDGE).locator(".open-link").click()
		page.locator(".acknowledgement .primary-button").click()
		expect(page.locator(".acknowledgement")).to_contain_text("You acknowledged this announcement on")
		toast.locator(".toast-close").click()
		page.keyboard.press("Escape")
		expect(page.locator(".window")).to_be_hidden()

		page.reload()
		expect(page.locator(".launcher-count")).to_have_text("1")
		# The toast would follow one more request.
		page.wait_for_timeout(2_000)
		expect(toast).to_have_count(0)
		page.locator(".launcher-main").click()
		announcements_tab = page.locator(".tab", has_text="Announcements")
		expect(announcements_tab).to_be_visible()
		expect(announcements_tab.locator(".tab-dot")).to_have_count(0)
		self.assertEqual([error for error in errors if "[attention_center]" in error], [])

	def test_an_immediate_announcement_published_before_the_page_loads(self):
		"""Its sticky toast shows when the page loads, until the Announcements tab was viewed [FR-ANN-02]."""
		announce(self, ANNOUNCEMENT, requires_acknowledgement=0)
		page, errors = self.open_desk("en", "light")
		toast = page.locator(".toast[data-level='immediate']")
		expect(toast).to_contain_text("New item in Announcements")
		# Other toasts leave after 8 s.
		page.wait_for_timeout(9_000)
		expect(toast).to_be_visible()

		with page.expect_response(lambda response: "attention_center.api.mark_seen" in response.url):
			toast.locator(".toast-action").click()
		expect(page.locator(".tab[aria-selected='true']")).to_contain_text("Announcements")
		expect(page.locator("tbody tr").first).to_contain_text(ANNOUNCEMENT)

		page.reload()
		expect(page.locator(".launcher-count")).to_have_text("1")
		# The toast would follow one more request.
		page.wait_for_timeout(2_000)
		expect(toast).to_have_count(0)
		self.assertEqual([error for error in errors if "[attention_center]" in error], [])

	def test_remind_me_later_sets_the_users_reminder_about_the_item(self):
		"""From the item's row, right to left: Frappe's Reminder of the user about the item's document [FR-SNZ-01]."""
		page, errors = self.open_desk("ar", "light")
		page.locator(".launcher-main").click()
		toggle = page.locator("tbody tr", has_text=ITEM).locator(".snooze-button")
		toggle.click()
		expect(toggle).to_have_attribute("aria-expanded", "true")
		choices = page.locator(".snooze-row:not([hidden])")
		choices.get_by_role("button", name="بعد ساعة").click()
		expect(choices.locator(".snooze-status")).to_contain_text("سيصلك تذكير في")
		if SCREENSHOTS:
			page.screenshot(path=os.path.join(SCREENSHOTS, "remind-me-later-ar.png"))

		reminders = state["admin"].get(
			"/api/resource/Reminder",
			params={
				"filters": json.dumps([["user", "=", USER]]),
				"fields": json.dumps(["name", "reminder_doctype", "reminder_docname", "description"]),
			},
		)
		rows = reminders.json()["data"]
		for row in rows:
			self.addCleanup(call, "DELETE", f"/api/resource/Reminder/{row['name']}")
		self.assertEqual(
			[(row["reminder_doctype"], row["reminder_docname"], row["description"]) for row in rows],
			[("ToDo", state["todo"], ITEM)],
		)
		self.assertEqual([error for error in errors if "[attention_center]" in error], [])


# The size of the box fixed elements are placed in. The desk's scrollbar takes its width off that box, but not off
# documentElement.clientWidth.
VIEWPORT = """() => {
	const probe = document.createElement("div");
	probe.style.cssText = "position: fixed; inset: 0; visibility: hidden; pointer-events: none";
	document.body.append(probe);
	const { width, height } = probe.getBoundingClientRect();
	probe.remove();
	return [width, height];
}"""


def edges(page, locator) -> tuple[float, float, float]:
	"""The distance of the element from the left, right and bottom edges of the box fixed elements are placed in."""
	box = locator.bounding_box()
	width, height = page.evaluate(VIEWPORT)
	return box["x"], width - box["x"] - box["width"], height - box["y"] - box["height"]


if __name__ == "__main__":
	unittest.main(verbosity=2)
