"""Browser checks for the operational overview, using API responses only."""
import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


WEB = Path(__file__).resolve().parents[1]
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
TOKEN = "x." + base64.urlsafe_b64encode(json.dumps({"exp": 4102444800, "email": "operator@example.test"}).encode()).decode().rstrip("=") + ".x"


def launch_browser(playwright):
    return playwright.chromium.launch(headless=True, **({"executable_path": str(CHROME)} if CHROME.exists() else {}))


class OverviewBrowser(unittest.TestCase):
    def test_action_queue_progress_freshness_and_mobile(self):
        now = datetime.now(timezone.utc)
        old_check = (now - timedelta(minutes=30)).isoformat()
        old_operation = (now - timedelta(minutes=50)).isoformat()
        lease = {"lease_id": "ls1", "name": "staging", "blueprint_ref": "web-db@1.0.0",
                 "expires_at": "2099-01-01T00:00:00Z", "mode": "schedule",
                 "environments": [{"name": "qa", "availability": "CHANGING"},
                                  {"name": "dev", "availability": "BLOCKED"}]}
        details = {**lease, "environments": [
            {"environment_id": "env-qa", "name": "qa", "availability": "CHANGING",
             "active_operation_id": "op-qa", "observed_at": old_check},
            {"environment_id": "env-dev", "name": "dev", "availability": "BLOCKED",
             "blocked_reason": {"code": "PLAN_UNSAFE", "detail": "Needs review"},
             "observed_at": old_check}]}
        operation = {"operation_id": "op-qa", "action": "WAKE", "status": "RUNNING",
                     "requested_at": old_operation}
        def mock(route):
            path = route.request.url.replace("https://mock.example", "")
            body = {"/v1/leases": {"items": [lease]}, "/v1/leases/ls1": details,
                    "/v1/environments/env-qa/operations": {"items": [operation]},
                    "/v1/environments/env-dev/operations": {"items": []},
                    "/v1/leases/ls1/cost": {"totals": {"always_on": 30, "stop_only": 20, "infraflow": 12}}}.get(path, {"items": []})
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            try:
                for width in (1440, 375):
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    page.add_init_script(f'window.INFRAFLOW={{apiUrl:"https://mock.example"}};sessionStorage.setItem("idToken","{TOKEN}");')
                    page.route("https://mock.example/**", mock)
                    page.goto((WEB / "index.html").as_uri() + "#/")
                    page.wait_for_selector("#overview-cost .overview-cost-bars")
                    self.assertIn("dev", page.locator("#overview-priority").inner_text())
                    self.assertIn("PLAN_UNSAFE", page.locator("#overview-priority").inner_text())
                    self.assertIn("qa", page.locator("#overview-active").inner_text())
                    self.assertIn("RUNNING", page.locator("#overview-active").inner_text())
                    self.assertIn("0 of 2 active Environments checked within 15 minutes", page.locator("#overview-freshness").inner_text())
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                    page.close()
            finally:
                browser.close()

    def test_old_failure_and_reclaimed_lease_are_not_urgent(self):
        lease = {"lease_id": "ls-old", "name": "finished", "blueprint_ref": "web-db@1.0.0",
                 "expires_at": "2020-01-01T00:00:00Z", "mode": "schedule",
                 "environments": [{"name": "qa", "availability": "RECLAIMED"}]}
        details = {**lease, "reclaim_requested": True, "environments": [
            {"environment_id": "env-old", "name": "qa", "status": "RECLAIMED",
             "availability": "RECLAIMED", "observed_at": "2020-01-01T00:00:00Z"}]}
        ops = {"items": [
            {"operation_id": "op-new", "action": "RECLAIM", "status": "SUCCEEDED", "requested_at": "2020-01-02T00:00:00Z"},
            {"operation_id": "op-old", "action": "WAKE", "status": "FAILED", "requested_at": "2020-01-01T00:00:00Z"}]}
        def mock(route):
            path = route.request.url.replace("https://mock.example", "")
            body = {"/v1/leases": {"items": [lease]}, "/v1/leases/ls-old": details,
                    "/v1/environments/env-old/operations": ops,
                    "/v1/leases/ls-old/cost": {"totals": {"always_on": 0, "stop_only": 0, "infraflow": 0}}}.get(path, {"items": []})
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            try:
                page = browser.new_page()
                page.add_init_script(f'window.INFRAFLOW={{apiUrl:"https://mock.example"}};sessionStorage.setItem("idToken","{TOKEN}");')
                page.route("https://mock.example/**", mock)
                page.goto((WEB / "index.html").as_uri() + "#/")
                page.wait_for_selector("#overview-cost:has-text('No active Lease estimates')")
                self.assertEqual(page.locator("#overview-priority .overview-count").inner_text(), "0")
                self.assertNotIn("WAKE FAILED", page.locator("#overview-priority").inner_text())
            finally:
                browser.close()

    def test_incomplete_details_do_not_show_an_unqualified_all_clear(self):
        lease = {"lease_id": "ls-missing", "name": "unavailable", "blueprint_ref": "web-db@1.0.0",
                 "expires_at": "2099-01-01T00:00:00Z", "mode": "schedule", "environments": []}
        def mock(route):
            path = route.request.url.replace("https://mock.example", "")
            if path == "/v1/leases/ls-missing":
                route.fulfill(status=503, content_type="application/json", body='{"error":{"code":"UNAVAILABLE","message":"Try again"}}')
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"items": [lease]} if path == "/v1/leases" else {"items": []}))
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            try:
                page = browser.new_page()
                page.add_init_script(f'window.INFRAFLOW={{apiUrl:"https://mock.example"}};sessionStorage.setItem("idToken","{TOKEN}");')
                page.route("https://mock.example/**", mock)
                page.goto((WEB / "index.html").as_uri() + "#/")
                page.wait_for_selector("#overview-priority:has-text('full picture is unavailable')")
                self.assertIn("Some data could not be loaded", page.locator("#overview-priority").inner_text())
                self.assertIn("1 Lease could not be loaded", page.locator("#overview-freshness").inner_text())
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
