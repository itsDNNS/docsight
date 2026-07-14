"""E2E tests for authentication flows."""

import pytest


class TestLoginPage:
    """Login page rendering."""

    def test_login_page_renders(self, auth_page, auth_server):
        auth_page.goto(auth_server)
        # Should redirect to /login
        assert "/login" in auth_page.url

    def test_login_page_title(self, auth_page, auth_server):
        auth_page.goto(f"{auth_server}/login")
        assert "DOCSight" in auth_page.title()

    def test_login_has_password_input(self, auth_page, auth_server):
        auth_page.goto(f"{auth_server}/login")
        pw = auth_page.locator('input[name="password"]')
        assert pw.is_visible()

    def test_login_has_submit_button(self, auth_page, auth_server):
        auth_page.goto(f"{auth_server}/login")
        btn = auth_page.locator('button[type="submit"]')
        assert btn.is_visible()


class TestLoginFlow:
    """Actual login/logout behavior."""

    def test_wrong_password_shows_error(self, auth_page, auth_server):
        auth_page.goto(f"{auth_server}/login")
        auth_page.fill('input[name="password"]', "wrong-password")
        auth_page.click('button[type="submit"]')
        error = auth_page.locator(".error")
        assert error.is_visible()

    def test_correct_password_redirects_to_dashboard(self, auth_page, auth_server):
        auth_page.goto(f"{auth_server}/login")
        auth_page.fill('input[name="password"]', "e2e-test-password")
        auth_page.click('button[type="submit"]')
        auth_page.wait_for_load_state("networkidle")
        # Should land on dashboard (not /login)
        assert "/login" not in auth_page.url

    def test_authenticated_can_access_settings(self, auth_page, auth_server):
        auth_page.goto(f"{auth_server}/login")
        auth_page.fill('input[name="password"]', "e2e-test-password")
        auth_page.click('button[type="submit"]')
        auth_page.wait_for_load_state("networkidle")
        auth_page.goto(f"{auth_server}/settings")
        assert "settings" in auth_page.url.lower() or "Settings" in auth_page.title()

    def test_sidebar_logout_button_logs_out_and_protects_dashboard(self, auth_page, auth_server):
        auth_page.goto(f"{auth_server}/login")
        auth_page.fill('input[name="password"]', "e2e-test-password")
        auth_page.click('button[type="submit"]')
        auth_page.wait_for_load_state("networkidle")

        logout_button = auth_page.locator('form[action="/logout"] button[type="submit"]')
        assert logout_button.is_visible()
        logout_button.click()
        auth_page.wait_for_url("**/login")

        auth_page.goto(auth_server)
        assert "/login" in auth_page.url

    def test_storage_state_restores_dashboard_session(self, auth_page, auth_server, browser):
        auth_page.goto(f"{auth_server}/login")
        auth_page.fill('input[name="password"]', "e2e-test-password")
        auth_page.click('button[type="submit"]')
        auth_page.wait_for_load_state("networkidle")
        storage_state = auth_page.context.storage_state()

        restored_context = browser.new_context(storage_state=storage_state)
        try:
            restored_page = restored_context.new_page()
            restored_page.goto(auth_server)
            restored_page.wait_for_load_state("networkidle")
            assert "/login" not in restored_page.url
        finally:
            restored_context.close()


class TestProtectedRoutes:
    """Unauthenticated access is blocked."""

    def test_dashboard_redirects_to_login(self, auth_page, auth_server):
        auth_page.goto(auth_server)
        assert "/login" in auth_page.url

    def test_settings_redirects_to_login(self, auth_page, auth_server):
        auth_page.goto(f"{auth_server}/settings")
        assert "/login" in auth_page.url

    def test_health_always_accessible(self, auth_page, auth_server):
        auth_page.goto(f"{auth_server}/health")
        content = auth_page.text_content("body")
        assert "ok" in content
