from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class TruecallerBrowserError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TruecallerBrowserResult:
    source: str
    number: str
    status: str
    display_name: str | None
    profile_label: str | None
    page_url: str | None
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TruecallerBrowserClient:
    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        *,
        timeout_seconds: float = 90.0,
        profile_dir: str | Path | None = None,
        headless: bool = False,
    ) -> None:
        self.analyzer = analyzer
        self.timeout_seconds = timeout_seconds
        self.profile_dir = Path(profile_dir or Path.home() / ".local/share/moriarty-v5/truecaller-browser")
        self.headless = headless

    def sign_out(self) -> bool:
        """Clear the persisted Truecaller browser session for account switching."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise TruecallerBrowserError("Playwright is not installed.") from exc
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    headless=True,
                    args=["--ozone-platform=x11"] if os.name != "nt" else [],
                    viewport={"width": 1365, "height": 900},
                    locale="en-US",
                )
                try:
                    context.clear_cookies()
                    page = context.pages[0] if context.pages else context.new_page()
                    page.goto("https://www.truecaller.com/", wait_until="domcontentloaded", timeout=30_000)
                    page.evaluate(
                        """async () => {
                            localStorage.clear();
                            sessionStorage.clear();
                            if ('caches' in window) {
                                for (const key of await caches.keys()) await caches.delete(key);
                            }
                            if (indexedDB.databases) {
                                for (const db of await indexedDB.databases()) {
                                    if (db.name) indexedDB.deleteDatabase(db.name);
                                }
                            }
                        }"""
                    )
                    context.clear_cookies()
                    return True
                finally:
                    context.close()
        except Exception as exc:
            raise TruecallerBrowserError(f"Could not clear the Truecaller session: {exc}") from exc

    def login(self) -> dict[str, Any]:
        """Open Truecaller's supported interactive login and persist the session.

        Passwords and OTP values are intentionally entered by the user directly
        into the identity provider page and never pass through Moriarty.
        """
        if self.headless:
            raise TruecallerBrowserError("Truecaller login requires a visible browser.")
        if os.name != "nt" and not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
            raise TruecallerBrowserError("Visible browser unavailable: DISPLAY/WAYLAND_DISPLAY is not set.")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise TruecallerBrowserError(
                "Playwright is not installed. Run: bash install.sh && "
                "~/.local/share/moriarty-v5/venv/bin/python -m playwright install chromium"
            ) from exc
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_seconds
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(self.profile_dir), headless=False, viewport=None, locale="en-US",
                args=["--ozone-platform=x11"] if os.name != "nt" else [],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(10_000)
                page.goto("https://www.truecaller.com/", wait_until="domcontentloaded", timeout=30_000)
                self._accept_cookies(page)
                if self._signed_in(page):
                    return {"source":"truecaller_browser","status":"already_authenticated","profile_dir":str(self.profile_dir)}
                self._click_named(page, "Sign in")
                page.wait_for_timeout(1_500)
                google_page = self._click_google(page)
                google_clicked = google_page is not None
                oauth_seen = False
                oauth_returned = False
                while time.monotonic() < deadline:
                    pages = tuple(context.pages)
                    if any(self._is_google_auth(candidate) for candidate in pages):
                        oauth_seen = True
                    if oauth_seen and not any(self._is_google_auth(candidate) for candidate in pages):
                        oauth_returned = True
                    if oauth_returned:
                        try:
                            page.bring_to_front()
                            page.goto("https://www.truecaller.com/", wait_until="domcontentloaded", timeout=20_000)
                            page.wait_for_timeout(1_500)
                            if self._signed_in(page):
                                return {"source":"truecaller_browser","status":"authenticated","profile_dir":str(self.profile_dir)}
                        except Exception:
                            pass
                        oauth_returned = False
                    page.wait_for_timeout(1_000)
                return {
                    "source":"truecaller_browser",
                    "status":"login_incomplete",
                    "profile_dir":str(self.profile_dir),
                    "note":"The login window timed out before Truecaller authentication was confirmed.",
                    "google_button_clicked":google_clicked,
                    "google_oauth_seen":oauth_seen,
                }
            finally:
                try:
                    context.close()
                except Exception:
                    pass

    def lookup_own_number(
        self,
        number: str,
        region: str | None = None,
        *,
        google_email: str | None = None,
        google_password: str | None = None,
        auth_provider: str = "microsoft",
        auth_email: str | None = None,
        auth_password: str | None = None,
    ) -> TruecallerBrowserResult:
        analysis = self.analyzer.analyze(number, region)
        if not analysis.is_valid:
            raise TruecallerBrowserError("A valid phone number is required.")
        login_email = auth_email or google_email
        login_password = auth_password or google_password
        if auth_provider == "microsoft" and (not login_email or not login_password):
            return self._status(
                analysis.e164,
                "configuration_required",
                "https://www.truecaller.com/",
                note="Truecaller is unavailable because Microsoft email and password were not provided during setup.",
            )
        automated_login_available = bool(login_email and login_password)
        if not self.headless and os.name != "nt" and not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
            raise TruecallerBrowserError("Visible browser unavailable: DISPLAY/WAYLAND_DISPLAY is not set.")
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise TruecallerBrowserError(
                "Playwright is not installed. Run: bash install.sh && "
                "~/.local/share/moriarty-v5/venv/bin/python -m playwright install chromium"
            ) from exc

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        timeout_ms = max(5_000, int(self.timeout_seconds * 1000))
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    headless=self.headless,
                    args=["--ozone-platform=x11"] if os.name != "nt" else [],
                    viewport=None if not self.headless else {"width": 1365, "height": 900},
                    locale="en-US",
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.set_default_timeout(min(timeout_ms, 15_000))
                    search_url = "https://www.truecaller.com/reverse-phone-number-lookup"
                    page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=min(timeout_ms, 30_000),
                    )
                    self._accept_cookies(page)
                    if self._verification_present(page):
                        return self._status(analysis.e164, "verification_required", page.url)
                    if self._login_present(page):
                        if self.headless and not automated_login_available:
                            return self._status(analysis.e164, "login_required", page.url)
                        if not self._login_in_context(
                            context, page, timeout_ms, auth_provider, login_email, login_password
                        ):
                            return self._status(analysis.e164, "login_required", page.url)
                        page.goto(search_url, wait_until="domcontentloaded", timeout=min(timeout_ms, 30_000))
                        page.wait_for_timeout(1_500)
                    field = self._phone_field(page)
                    if field is None:
                        status = "login_required" if self._login_present(page) else "page_changed"
                        return self._status(analysis.e164, status, page.url)
                    field.fill(analysis.e164)
                    field.press("Enter")
                    page.wait_for_timeout(2_000)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 20_000))
                    except PlaywrightTimeoutError:
                        pass
                    if self._search_limit_exceeded(page):
                        return self._status(analysis.e164, "search_limit_exceeded", page.url)
                    if self._verification_present(page):
                        return self._status(analysis.e164, "verification_required", page.url)
                    if self._login_present(page):
                        if self.headless and not automated_login_available:
                            return self._status(analysis.e164, "login_required", page.url)
                        if not self._login_in_context(
                            context, page, timeout_ms, auth_provider, login_email, login_password
                        ):
                            return self._status(analysis.e164, "login_required", page.url)
                        page.goto(search_url, wait_until="domcontentloaded", timeout=min(timeout_ms, 30_000))
                        page.wait_for_timeout(1_500)
                        field = self._phone_field(page)
                        if field is None:
                            return self._status(analysis.e164, "page_changed", page.url)
                        field.fill(analysis.e164)
                        field.press("Enter")
                        page.wait_for_timeout(2_000)
                        if self._search_limit_exceeded(page):
                            return self._status(analysis.e164, "search_limit_exceeded", page.url)
                    try:
                        page.get_by_text(re.compile(r"save contact|suggest name", re.I)).first.wait_for(
                            state="visible", timeout=min(timeout_ms, 15_000)
                        )
                    except Exception:
                        pass
                    name, label = self._extract_identity(page, analysis.e164)
                    if not name:
                        return self._status(analysis.e164, "not_found", page.url)
                    return TruecallerBrowserResult(
                        source="truecaller_browser",
                        number=analysis.e164,
                        status="found",
                        display_name=name,
                        profile_label=label,
                        page_url=page.url,
                        note="Truecaller profile label observed through the user's browser session; not proof of legal ownership.",
                    )
                finally:
                    try:
                        context.close()
                    except Exception:
                        pass
        except KeyboardInterrupt:
            raise
        except PlaywrightTimeoutError as exc:
            raise TruecallerBrowserError("Truecaller browser operation timed out.") from exc
        except TruecallerBrowserError:
            raise
        except Exception as exc:
            raise TruecallerBrowserError(f"Truecaller browser failed: {exc}") from exc

    @staticmethod
    def _accept_cookies(page: Any) -> None:
        for label in ("Accept all", "Accept", "Allow all", "I agree"):
            button = page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$", re.I))
            if button.count():
                try:
                    button.first.click(timeout=1_500)
                    return
                except Exception:
                    continue

    @staticmethod
    def _phone_field(page: Any) -> Any | None:
        candidates = (
            page.locator('input[type="tel"]'),
            page.locator('input[name*="phone" i]'),
            page.locator('input[placeholder*="phone" i]'),
            page.locator('input[aria-label*="phone" i]'),
        )
        for locator in candidates:
            if locator.count() and locator.first.is_visible():
                return locator.first
        return None

    @staticmethod
    def _verification_present(page: Any) -> bool:
        text = page.locator("body").inner_text(timeout=3_000).lower()
        return any(value in text for value in ("captcha", "verify you are human", "not a robot", "unusual traffic"))

    @staticmethod
    def _login_present(page: Any) -> bool:
        text = page.locator("body").inner_text(timeout=3_000).lower()
        if any(value in text for value in ("sign in to continue", "log in to continue", "login to continue")):
            return True
        for role in ("button", "link"):
            try:
                controls = page.get_by_role(role, name=re.compile(r"^sign in$", re.I))
                for index in range(controls.count()):
                    if controls.nth(index).is_visible():
                        return True
            except Exception:
                continue
        return False

    @staticmethod
    def _signed_in(page: Any) -> bool:
        try:
            if "/auth/" in page.url or "accounts.google.com" in page.url:
                return False
            text = page.locator("body").inner_text(timeout=3_000).lower()
            if any(value in text for value in ("my profile", "sign out", "log out", "account settings")):
                return True
            for selector in (
                '[aria-label*="account" i]', '[aria-label*="profile" i]',
                '[data-testid*="account" i]', '[data-testid*="profile" i]',
                'a[href*="/profile"]', 'button[class*="avatar" i]',
            ):
                target = page.locator(selector)
                if target.count() and target.first.is_visible():
                    return not TruecallerBrowserClient._login_present(page)
            
            
            
            if "truecaller.com" in page.url and not TruecallerBrowserClient._login_present(page):
                field = TruecallerBrowserClient._phone_field(page)
                if field is not None and field.is_visible():
                    return True
            return False
        except Exception:
            return False

    @staticmethod
    def _is_google_auth(page: Any) -> bool:
        try:
            host = page.url.lower()
            return "accounts.google.com" in host or "accounts.youtube.com" in host
        except Exception:
            return False

    @staticmethod
    def _click_named(page: Any, name: str) -> None:
        pattern = re.compile(rf"^{re.escape(name)}$", re.I)
        for role in ("button", "link"):
            target = page.get_by_role(role, name=pattern)
            if target.count():
                target.first.click()
                return
        target = page.get_by_text(pattern, exact=True)
        if target.count():
            target.first.click()
            return
        raise TruecallerBrowserError(f"Truecaller '{name}' control was not found; the page may have changed.")

    @staticmethod
    def _click_google(page: Any) -> Any | None:
        """Click the OAuth provider without depending on one DOM implementation."""
        pattern = re.compile(r"google", re.I)
        deadline = time.monotonic() + 8.0
        context = page.context
        captured: list[Any] = []

        def remember_popup(candidate: Any) -> None:
            captured.append(candidate)

        context.on("page", remember_popup)
        while time.monotonic() < deadline:
            for frame in tuple(page.frames):
                candidates = (
                    frame.get_by_role("button", name=pattern),
                    frame.get_by_role("link", name=pattern),
                    frame.locator('button:has-text("Google")'),
                    frame.locator('[role="button"]:has-text("Google")'),
                    frame.locator('a:has-text("Google")'),
                    frame.locator('[data-provider*="google" i]'),
                    frame.locator('[class*="google" i]'),
                )
                for target in candidates:
                    try:
                        if target.count() and target.first.is_visible():
                            target.first.click(timeout=3_000)
                            
                            
                            
                            popup_deadline = deadline
                            while time.monotonic() < popup_deadline:
                                for candidate in tuple(captured) + tuple(context.pages):
                                    if TruecallerBrowserClient._is_google_auth(candidate):
                                        return candidate
                                if TruecallerBrowserClient._is_google_auth(page):
                                    return page
                                page.wait_for_timeout(250)
                            return None
                    except Exception:
                        continue
            page.wait_for_timeout(500)
        
        
        return None

    def _login_in_context(
        self,
        context: Any,
        page: Any,
        timeout_ms: int,
        auth_provider: str = "microsoft",
        auth_email: str | None = None,
        auth_password: str | None = None,
    ) -> bool:
        """Complete an interactive OAuth login without reading credentials."""
        try:
            self._click_named(page, "Sign in")
            page.wait_for_timeout(1_500)
            provider_page = self._click_identity_provider(page, auth_provider)
        except TruecallerBrowserError:
            return False
        if auth_email and auth_password and provider_page is not None:
            if auth_provider == "microsoft":
                self._enter_microsoft_credentials(context, provider_page, auth_email, auth_password)
            else:
                self._enter_google_credentials(provider_page, auth_email, auth_password)
        deadline = time.monotonic() + min(self.timeout_seconds, timeout_ms / 1000)
        oauth_seen = provider_page is not None
        while time.monotonic() < deadline:
            pages = tuple(context.pages)
            if any(self._is_auth_page(candidate, auth_provider) for candidate in pages):
                oauth_seen = True
            if self._authentication_failed(pages, auth_provider):
                return False
            for candidate in pages:
                try:
                    if TruecallerBrowserClient._recover_truecaller_callback(candidate):
                        return True
                    if oauth_seen and "truecaller.com" in candidate.url and self._signed_in(candidate):
                        return True
                except Exception:
                    continue
            page.wait_for_timeout(1_000)
        return False

    @staticmethod
    def _click_identity_provider(page: Any, provider: str) -> Any | None:
        if provider == "google":
            return TruecallerBrowserClient._click_google(page)
        if provider != "microsoft":
            raise TruecallerBrowserError(f"Unsupported Truecaller authentication provider: {provider}")
        return TruecallerBrowserClient._click_oauth_button(page, "Microsoft", "microsoft")

    @staticmethod
    def _click_oauth_button(page: Any, label: str, provider: str) -> Any | None:
        pattern = re.compile(label, re.I)
        context = page.context
        captured: list[Any] = []
        context.on("page", lambda candidate: captured.append(candidate))
        candidates = (
            page.get_by_role("button", name=pattern),
            page.get_by_role("link", name=pattern),
            page.locator(f'button:has-text("{label}")'),
            page.locator(f'[role="button"]:has-text("{label}")'),
            page.locator(f'[class*="{provider}" i]'),
        )
        deadline = time.monotonic() + 12.0
        for target in candidates:
            if time.monotonic() >= deadline:
                break
            try:
                if not target.count() or not target.first.is_visible():
                    continue
                remaining_ms = max(500, int((deadline - time.monotonic()) * 1000))
                target.first.click(timeout=min(3_000, remaining_ms))
                while time.monotonic() < deadline:
                    for candidate in tuple(captured) + tuple(context.pages):
                        if TruecallerBrowserClient._is_auth_page(candidate, provider):
                            return candidate
                    page.wait_for_timeout(250)
            except Exception:
                continue
        return None

    @staticmethod
    def _authentication_failed(pages: tuple[Any, ...], provider: str) -> bool:
        """Stop waiting when the identity provider visibly rejected login."""
        markers = (
            "we couldn't sign you in",
            "we could not sign you in",
            "account or password is incorrect",
            "sign-in is blocked",
            "sign in is blocked",
            "couldn't find your google account",
            "wrong password",
            "access blocked",
        )
        for candidate in pages:
            if not TruecallerBrowserClient._is_auth_page(candidate, provider):
                continue
            try:
                text = candidate.locator("body").inner_text(timeout=1_500).casefold()
            except Exception:
                continue
            if any(marker in text for marker in markers):
                return True
        return False

    @staticmethod
    def _is_auth_page(page: Any, provider: str) -> bool:
        if provider == "google":
            return TruecallerBrowserClient._is_google_auth(page)
        try:
            url = page.url.lower()
            return any(host in url for host in ("login.live.com", "login.microsoftonline.com", "account.live.com"))
        except Exception:
            return False

    @staticmethod
    def _enter_microsoft_credentials(context: Any, page: Any, email: str, password: str) -> None:
        try:
            print("Microsoft login page detected; waiting for email field...", file=sys.stderr)
            page.bring_to_front()
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30_000)
            except Exception:
                pass
            email_field = page.locator("#i0116, input[name='loginfmt'], input[type='email']").first
            email_field.wait_for(state="visible", timeout=30_000)
            email_field.fill(email)
            if email_field.input_value() != email:
                email_field.click(); page.keyboard.press("Control+A"); page.keyboard.type(email, delay=40)
            if email_field.input_value() != email:
                print("Microsoft email field could not be populated; complete login manually.", file=sys.stderr); return
            print("Microsoft email entered; continuing to password step...", file=sys.stderr)
            page.locator("#idSIButton9, button[type='submit'], input[type='submit']").first.click()
            password_field = TruecallerBrowserClient._reach_microsoft_password(page)
            password_field.fill(password)
            if password_field.input_value() != password:
                password_field.click(); page.keyboard.press("Control+A"); page.keyboard.type(password, delay=40)
            if password_field.input_value() != password:
                print("Microsoft password field could not be populated; complete login manually.", file=sys.stderr); return
            print("Microsoft password entered; submitting login...", file=sys.stderr)
            page.locator("#idSIButton9, button[type='submit'], input[type='submit']").first.click()
            TruecallerBrowserClient._advance_microsoft_after_password(context, page, password)
        except Exception as exc:
            print(f"Microsoft form automation paused: {type(exc).__name__}. Complete login manually.", file=sys.stderr)

    @staticmethod
    def _advance_microsoft_after_password(context: Any, original_page: Any, password: str) -> None:
        transitions = 0
        deadline = time.monotonic() + 75.0
        while time.monotonic() < deadline:
            pages = tuple(context.pages)
            if any("truecaller.com" in candidate.url for candidate in pages):
                for candidate in pages:
                    if TruecallerBrowserClient._recover_truecaller_callback(candidate):
                        return
                    if "truecaller.com" in candidate.url and TruecallerBrowserClient._signed_in(candidate):
                        return
            microsoft_pages = [
                candidate for candidate in pages
                if TruecallerBrowserClient._is_auth_page(candidate, "microsoft")
            ]
            if not microsoft_pages:
                microsoft_pages = [original_page]
            transitioned = False
            
            
            
            for page in microsoft_pages:
                try:
                    body = page.locator("body").inner_text(timeout=2_000).lower()
                    consent_page = (
                        "let this app access your info" in body
                        or "truecaller needs your permission" in body
                        or "bu uygulamanın bilgilerinize erişmesine izin ver" in body
                    )
                    if consent_page and TruecallerBrowserClient._click_microsoft_consent(page):
                        print("Microsoft Truecaller permission detected; accepting...", file=sys.stderr)
                        transitions += 1
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=10_000)
                        except Exception:
                            page.wait_for_timeout(1_200)
                        transitioned = True
                        break
                except Exception:
                    continue
            if transitioned:
                continue
            for page in microsoft_pages:
                try:
                    if TruecallerBrowserClient._click_microsoft_text(
                        page, ("other ways to sign in", "diğer oturum açma yöntemleri")
                    ):
                        if transitions >= 8:
                            return
                        print("Post-password 'Other ways to sign in' detected; opening alternate methods...", file=sys.stderr)
                        transitions += 1
                        page.wait_for_timeout(900)
                        transitioned = True
                        break
                except Exception:
                    continue
            if transitioned:
                continue
            for page in microsoft_pages:
                try:
                    if TruecallerBrowserClient._click_microsoft_text(
                        page, ("use your password", "parolanızı kullanın")
                    ):
                        if transitions >= 8:
                            return
                        print("Post-password password option detected; selecting it...", file=sys.stderr)
                        transitions += 1
                        page.wait_for_timeout(900)
                        password_field = page.locator("#i0118, input[name='passwd'], input[type='password']").first
                        password_field.wait_for(state="visible", timeout=20_000)
                        password_field.fill(password)
                        page.locator("#idSIButton9, button[type='submit'], input[type='submit']").first.click()
                        page.wait_for_timeout(900)
                        transitioned = True
                        break
                except Exception:
                    continue
            if transitioned:
                continue
            
            
            try:
                page = microsoft_pages[0]
                body = page.locator("body").inner_text(timeout=2_000).lower()
                if "stay signed in" in body or "oturumunuz açık kalsın" in body:
                    no = page.locator("#idBtn_Back")
                    if not no.count():
                        no = page.get_by_role("button", name=re.compile(r"^(no|hayır)$", re.I))
                    if no.count() and no.first.is_visible():
                        print("Declining Microsoft persistent-session prompt...", file=sys.stderr)
                        no.first.click()
                        page.wait_for_timeout(900)
                        continue
            except Exception:
                pass
            page.wait_for_timeout(500)

    @staticmethod
    def _recover_truecaller_callback(page: Any) -> bool:
        """Escape a completed Truecaller OAuth callback that remains on a spinner."""
        try:
            url = page.url.lower()
            if "truecaller.com/auth/" not in url or "/callback" not in url:
                return False
            
            
            
            
            print("Truecaller OAuth callback detected; waiting for the session to settle...", file=sys.stderr)
            page.wait_for_timeout(8_000)
            print("Truecaller OAuth callback completed; returning to dashboard...", file=sys.stderr)
            page.goto("https://www.truecaller.com/", wait_until="domcontentloaded", timeout=30_000)
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline:
                if TruecallerBrowserClient._signed_in(page):
                    return True
                page.wait_for_timeout(1_000)
            return False
        except Exception:
            return False

    @staticmethod
    def _reach_microsoft_password(page: Any) -> Any:
        password_field = page.locator("#i0118, input[name='passwd'], input[type='password']").first
        transition_count = 0
        max_transitions = 8
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            try:
                if password_field.is_visible():
                    print("Microsoft password field detected.", file=sys.stderr)
                    return password_field
            except Exception:
                pass
            try:
                if TruecallerBrowserClient._click_microsoft_text(
                    page, ("use your password", "parolanızı kullanın")
                ):
                    if transition_count >= max_transitions:
                        raise TruecallerBrowserError("Microsoft authentication produced too many intermediate screens.")
                    print("Selecting Microsoft password authentication...", file=sys.stderr)
                    transition_count += 1
                    page.wait_for_timeout(900)
                    continue
            except TruecallerBrowserError:
                raise
            except Exception:
                pass
            try:
                if TruecallerBrowserClient._click_microsoft_text(
                    page, ("other ways to sign in", "diğer oturum açma yöntemleri")
                ):
                    if transition_count >= max_transitions:
                        raise TruecallerBrowserError("Microsoft authentication produced too many intermediate screens.")
                    print("Other ways to sign in detected; opening alternate methods...", file=sys.stderr)
                    transition_count += 1
                    page.wait_for_timeout(900)
                    continue
            except TruecallerBrowserError:
                raise
            except Exception:
                pass
            page.wait_for_timeout(400)
        raise TruecallerBrowserError("Microsoft password form did not become available.")

    @staticmethod
    def _microsoft_control(page: Any, pattern: re.Pattern[str]) -> Any:
        """Return visible Microsoft auth controls across changing DOM variants."""
        candidates = (
            page.get_by_role("link", name=pattern),
            page.get_by_role("button", name=pattern),
            page.locator("a, button, [role='link'], [role='button']").filter(has_text=pattern),
            page.get_by_text(pattern),
        )
        for candidate in candidates:
            try:
                for index in range(candidate.count()):
                    if candidate.nth(index).is_visible():
                        return candidate.nth(index)
            except Exception:
                continue
        return page.locator(".__moriarty_missing_control__")

    @staticmethod
    def _click_microsoft_text(page: Any, phrases: tuple[str, ...]) -> bool:
        """Click a visible auth control by DOM text, including iframe variants."""
        pattern = re.compile("|".join(re.escape(item) for item in phrases), re.I)
        text_seen = False
        for frame in tuple(page.frames):
            try:
                locator = frame.get_by_text(pattern)
                for index in range(locator.count()):
                    target = locator.nth(index)
                    if not target.is_visible():
                        continue
                    text_seen = True
                    try:
                        target.click(force=True, timeout=3_000)
                        return True
                    except Exception:
                        try:
                            box = target.bounding_box()
                            if box:
                                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                return True
                        except Exception:
                            continue
            except Exception:
                continue
        script = """
        phrases => {
          const normalize = value => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
          const wanted = phrases.map(normalize);
          const nodes = [...document.querySelectorAll('a,button,[role="link"],[role="button"],input[type="button"],input[type="submit"]')];
          const target = nodes.find(node => {
            const text = normalize(node.innerText || node.textContent || node.value || node.getAttribute('aria-label'));
            const style = window.getComputedStyle(node);
            const visible = style.display !== 'none' && style.visibility !== 'hidden' && node.getClientRects().length > 0;
            return visible && wanted.some(value => text.includes(value));
          });
          if (!target) return false;
          target.scrollIntoView({block: 'center'});
          target.click();
          return true;
        }
        """
        for frame in tuple(page.frames):
            try:
                if frame.evaluate(script, list(phrases)):
                    return True
            except Exception:
                continue
        if text_seen:
            print(f"Microsoft control text was visible but could not be clicked: {phrases[0]}", file=sys.stderr)
        return False

    @staticmethod
    def _click_microsoft_consent(page: Any) -> bool:
        """Click only the actual Microsoft OAuth consent submit control."""
        exact = re.compile(r"^(accept|allow|kabul et|izin ver)$", re.I)
        for frame in tuple(page.frames):
            candidates = (
                frame.get_by_role("button", name=exact, exact=True),
                frame.locator(
                    'input[type="submit"][value="Accept" i], '
                    'input[type="submit"][value="Allow" i], '
                    'button:has-text("Accept"), button:has-text("Allow")'
                ),
            )
            for candidate in candidates:
                try:
                    for index in range(candidate.count()):
                        target = candidate.nth(index)
                        if not target.is_visible():
                            continue
                        label = (
                            target.get_attribute("value")
                            or target.get_attribute("aria-label")
                            or target.inner_text()
                            or ""
                        ).strip()
                        if not exact.fullmatch(label):
                            continue
                        target.click(timeout=5_000)
                        return True
                except Exception:
                    continue
        return False

    @staticmethod
    def _enter_google_credentials(google_page: Any, email: str, password: str) -> None:
        """Fill Google's visible form without storing or logging credentials."""
        try:
            print("Google login page detected; waiting for email field...", file=sys.stderr)
            google_page.bring_to_front()
            try:
                google_page.wait_for_load_state("domcontentloaded", timeout=30_000)
            except Exception:
                pass
            email_field = google_page.locator("#identifierId")
            if not email_field.count():
                email_field = google_page.locator('input[type="email"]')
            email_field.first.wait_for(state="visible", timeout=30_000)
            email_field.first.click()
            email_field.first.fill(email)
            if email_field.first.input_value() != email:
                email_field.first.press("Control+A")
                email_field.first.press_sequentially(email, delay=35)
            if email_field.first.input_value() != email:
                email_field.first.click()
                google_page.keyboard.press("Control+A")
                google_page.keyboard.type(email, delay=50)
            if email_field.first.input_value() != email:
                print("Google email field could not be populated after keyboard fallback; complete login manually.", file=sys.stderr)
                return
            print("Google email entered; continuing to password step...", file=sys.stderr)
            next_button = google_page.locator("#identifierNext")
            if next_button.count():
                next_button.first.click()
            else:
                google_page.get_by_role("button", name=re.compile(r"^(next|sonraki)$", re.I)).first.click()
            password_field = google_page.locator('input[type="password"]')
            password_field.first.wait_for(state="visible", timeout=30_000)
            password_field.first.click()
            password_field.first.fill(password)
            if password_field.first.input_value() != password:
                password_field.first.press("Control+A")
                password_field.first.press_sequentially(password, delay=35)
            if password_field.first.input_value() != password:
                print("Google password field could not be populated; complete login manually.", file=sys.stderr)
                return
            print("Google password entered; submitting login...", file=sys.stderr)
            next_button = google_page.locator("#passwordNext")
            if next_button.count():
                next_button.first.click()
            else:
                google_page.get_by_role("button", name=re.compile(r"^(next|sonraki)$", re.I)).first.click()
        except Exception as exc:
            
            
            print(f"Google form automation paused: {type(exc).__name__}. Complete login manually.", file=sys.stderr)
            return

    @staticmethod
    def _extract_identity(page: Any, e164: str) -> tuple[str | None, str | None]:
        blocked = {
            "truecaller", "reverse phone number lookup", "phone number search",
            "search phone number", "unknown", "no results found", "sign in",
        }
        digits = re.sub(r"\D", "", e164)
        
        
        try:
            lines = [" ".join(value.split()).strip() for value in page.locator("body").inner_text(timeout=5_000).splitlines()]
            lines = [value for value in lines if value]
            action_indexes = [
                index for index, value in enumerate(lines)
                if value.lower() in {"save contact", "suggest name", "mark as spam"}
            ]
            for action_index in action_indexes:
                for index in range(action_index - 1, max(-1, action_index - 7), -1):
                    value = lines[index]
                    lowered = value.lower()
                    compact_digits = re.sub(r"\D", "", value)
                    if lowered in blocked or any(item in lowered for item in blocked):
                        continue
                    if compact_digits and compact_digits in (digits, digits[-10:]):
                        continue
                    if len(value) == 1 or value.upper() in {"TR", "EN"}:
                        continue
                    if 2 <= len(value) <= 120 and re.search(r"[A-Za-zÀ-žĞğİıŞşÇçÖöÜü]", value):
                        return value, value
        except Exception:
            pass
        for selector in (
            '[data-testid*="name" i]', '[class*="profile-name" i]',
            '[class*="caller-name" i]', "main h1", "main h2", "h1", "h2",
        ):
            locator = page.locator(selector)
            for index in range(min(locator.count(), 12)):
                try:
                    value = " ".join(locator.nth(index).inner_text().split()).strip()
                except Exception:
                    continue
                lowered = value.lower()
                if not value or lowered in blocked or any(item in lowered for item in blocked):
                    continue
                if re.sub(r"\D", "", value) in (digits, digits[-10:]):
                    continue
                if 2 <= len(value) <= 120 and re.search(r"[A-Za-zÀ-žĞğİıŞşÇçÖöÜü]", value):
                    return value, value
        return None, None

    @staticmethod
    def _status(number: str, status: str, url: str | None, note: str | None = None) -> TruecallerBrowserResult:
        notes = {
            "verification_required": "Truecaller displayed a human-verification screen; it was not bypassed.",
            "login_required": "Sign in once in the visible persistent browser profile, then run the command again.",
            "search_limit_exceeded": "Truecaller search limit has been reached for this account. Try again after the limit resets.",
            "page_changed": "The Truecaller search field was not found; the page layout may have changed.",
            "not_found": "No reliable profile label was found for the exact number.",
        }
        return TruecallerBrowserResult("truecaller_browser", number, status, None, None, url, note or notes.get(status, status))

    @staticmethod
    def _search_limit_exceeded(page: Any) -> bool:
        try:
            text = page.locator("body").inner_text(timeout=3_000)
            return bool(re.search(r"search\s+limit\s+exceeded", text, re.I))
        except Exception:
            return False
