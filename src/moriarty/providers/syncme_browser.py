from __future__ import annotations

import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer
from moriarty.providers.truecaller_browser import TruecallerBrowserClient


class SyncMeBrowserError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SyncMeBrowserResult:
    source: str
    number: str
    status: str
    display_name: str | None
    line_type: str | None
    address: str | None
    page_url: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SyncMeBrowserClient:
    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        *,
        timeout_seconds: float = 90.0,
        profile_dir: str | Path | None = None,
        headless: bool = True,
    ) -> None:
        self.analyzer = analyzer
        self.timeout_seconds = timeout_seconds
        self.profile_dir = Path(profile_dir or Path.home() / ".local/share/moriarty-v5/syncme-browser")
        self.headless = headless

    def lookup_own_number(
        self,
        number: str,
        region: str | None = None,
        *,
        microsoft_email: str | None = None,
        microsoft_password: str | None = None,
    ) -> SyncMeBrowserResult:
        analysis = self.analyzer.analyze(number, region)
        if not analysis.is_valid:
            raise SyncMeBrowserError("A valid phone number is required.")
        if not microsoft_email or not microsoft_password:
            return SyncMeBrowserResult(
                "syncme_browser", analysis.e164, "configuration_required",
                None, None, None, "https://sync.me/",
                "Sync.me is unavailable because Microsoft email and password were not provided during setup.",
            )
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SyncMeBrowserError("Playwright is not installed. Run: bash install.sh") from exc

        digits = re.sub(r"\D", "", analysis.e164)
        search_url = f"https://sync.me/search/?number={digits}"
        timeout_ms = max(5_000, int(self.timeout_seconds * 1000))
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    headless=self.headless,
                    viewport={"width": 1365, "height": 900} if self.headless else None,
                    locale="en-US",
                    args=((
                        (["--ozone-platform=x11"] if sys.platform != "win32" else [])
                        + (["--start-maximized"] if not self.headless else [])
                        + [
                            "--disable-save-password-bubble",
                            "--disable-features=PasswordManagerOnboarding,PasswordLeakDetection",
                        ]
                    )),
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.set_default_timeout(min(timeout_ms, 15_000))
                    
                    
                    
                    
                    page.goto(
                        "https://sync.me/",
                        wait_until="domcontentloaded",
                        timeout=min(timeout_ms, 30_000),
                    )
                    self._accept_cookies(page)
                    page.wait_for_timeout(1_500)
                    page.goto(search_url, wait_until="domcontentloaded", timeout=min(timeout_ms, 30_000))
                    page.wait_for_timeout(2_000)
                    body = page.locator("body").inner_text(timeout=min(timeout_ms, 15_000))
                    if self._locked(body) and microsoft_email and microsoft_password:
                        page.goto("https://sync.me/", wait_until="domcontentloaded", timeout=min(timeout_ms, 30_000))
                        self._accept_cookies(page)
                        if not self._login_microsoft(context, page, microsoft_email, microsoft_password, timeout_ms):
                            return self._parse(analysis.e164, page.url, body)
                        page.goto(search_url, wait_until="domcontentloaded", timeout=min(timeout_ms, 30_000))
                        page.wait_for_timeout(2_500)
                        body = page.locator("body").inner_text(timeout=min(timeout_ms, 15_000))
                    return self._parse(analysis.e164, page.url, body)
                finally:
                    context.close()
        except SyncMeBrowserError:
            raise
        except Exception as exc:
            raise SyncMeBrowserError(f"Sync.me browser failed: {exc}") from exc

    @staticmethod
    def _parse(number: str, url: str, body: str) -> SyncMeBrowserResult:
        compact = " ".join(body.split())
        lowered = compact.lower()
        url_lowered = url.lower()
        subscription_required = (
            "/pricing/" in url_lowered
            or "get my plan" in lowered
            or "unlimited annually" in lowered
            or "unlimited weekly" in lowered
            or "full caller id & advanced spam protection" in lowered
        )
        if subscription_required:
            return SyncMeBrowserResult(
                "syncme_browser",
                number,
                "subscription_required",
                None,
                None,
                None,
                url,
                "Sync.me redirected this account to its pricing page. The account's free search allowance appears exhausted; no lookup result was collected.",
            )
        line_type = None
        for candidate in ("Fixed Line or Mobile", "Fixed Line", "Mobile", "UAN", "VoIP"):
            if candidate.lower() in lowered:
                line_type = candidate
                break
        address = None
        match = re.search(r"\bAddress\s+([^|]{2,80}?)(?:\s+Sign in|\s+Always know|$)", compact, re.I)
        if not match:
            match = re.search(r"\bKonum:\s*([^|]{2,80}?)(?:\s+Spam|\s+Dolandırıcılık|$)", compact, re.I)
        if match:
            address = match.group(1).strip()
        name = None
        name_match = re.search(
            r"(?:\bİsim|\bIsim|\bName)\s*:\s*(.{2,120}?)(?=\s+(?:Konum|Location|Address|Spam|Dolandırıcılık)\b|$)",
            compact,
            re.I,
        )
        if name_match:
            name = name_match.group(1).strip(" -–—")
        locked = SyncMeBrowserClient._locked(compact)
        status = "found" if name else ("login_required" if locked else "not_found")
        note = (
            "Sync.me caller name observed through the user's paid browser session; not proof of legal ownership."
            if name
            else "Sync.me requires a signed-in persistent browser session to reveal the caller name."
            if locked
            else "No reliable caller name was found on the Sync.me result page."
        )
        return SyncMeBrowserResult("syncme_browser", number, status, name, line_type, address, url, note)

    @staticmethod
    def _locked(body: str) -> bool:
        lowered = body.lower()
        return any(value in lowered for value in (
            "sign in to unlock name", "sign in to unlock them", "oturum açın", "giriş yaparak"
        ))

    @staticmethod
    def _accept_cookies(page: Any) -> None:
        pattern = re.compile(r"^(accept all cookies|allow all cookies|tüm çerezleri kabul et)$", re.I)
        for frame in tuple(page.frames):
            for locator in (
                frame.get_by_role("button", name=pattern, exact=True),
                frame.locator("button, input[type='button'], input[type='submit']"),
            ):
                try:
                    for index in range(locator.count()):
                        target = locator.nth(index)
                        if not target.is_visible():
                            continue
                        label = (
                            target.get_attribute("value")
                            or target.get_attribute("aria-label")
                            or target.inner_text()
                            or ""
                        ).strip()
                        if not pattern.fullmatch(label):
                            continue
                        target.click(timeout=5_000)
                        page.wait_for_timeout(700)
                        return
                except Exception:
                    continue

    def _login_microsoft(self, context: Any, page: Any, email: str, password: str, timeout_ms: int) -> bool:
        sign_in = re.compile(r"^(sign in|giriş yap)$", re.I)
        clicked = self._click_exact(page, sign_in)
        if not clicked:
            menu_candidates = (
                page.locator("button.navbar-toggler, .navbar-toggler, [data-bs-toggle='collapse']"),
                page.locator("button[aria-label*='menu' i], [role='button'][aria-label*='menu' i]"),
            )
            for menu in menu_candidates:
                try:
                    if menu.count() and menu.first.is_visible():
                        menu.first.click(timeout=5_000)
                        page.wait_for_timeout(600)
                        break
                except Exception:
                    continue
            clicked = self._click_exact(page, sign_in)
        if not clicked:
            print("Sync.me Sign in control was not found after opening the navigation menu.", file=sys.stderr)
            return False
        page.wait_for_timeout(900)
        microsoft = re.compile(r"microsoft(?:\s+ile)?\s+(?:giriş yap|oturum aç)|sign in with microsoft", re.I)
        for locator in (page.get_by_role("button", name=microsoft), page.get_by_text(microsoft)):
            try:
                if locator.count() and locator.first.is_visible():
                    locator.first.click(timeout=5_000)
                    break
            except Exception:
                continue
        deadline = time.monotonic() + min(30.0, timeout_ms / 1000)
        auth_page = None
        while time.monotonic() < deadline:
            for candidate in tuple(context.pages):
                if TruecallerBrowserClient._is_auth_page(candidate, "microsoft"):
                    auth_page = candidate
                    break
            if auth_page is not None:
                break
            page.wait_for_timeout(250)
        if auth_page is None:
            return False
        print("Sync.me Microsoft login page detected; waiting for email field...", file=sys.stderr)
        auth_page.bring_to_front()
        email_field = auth_page.locator("#i0116, input[name='loginfmt'], input[type='email']").first
        email_field.wait_for(state="visible", timeout=30_000)
        email_field.fill(email)
        auth_page.locator("#idSIButton9, button[type='submit'], input[type='submit']").first.click()
        password_field = TruecallerBrowserClient._reach_microsoft_password(auth_page)
        password_field.fill(password)
        print("Sync.me Microsoft password entered; submitting login...", file=sys.stderr)
        
        
        
        try:
            password_field.press("Enter")
        except Exception:
            
            
            pass
        return self._finish_microsoft_login(context, auth_page, password, timeout_ms)

    @staticmethod
    def _click_exact(page: Any, pattern: re.Pattern[str]) -> bool:
        for locator in (
            page.get_by_role("link", name=pattern, exact=True),
            page.get_by_role("button", name=pattern, exact=True),
            page.get_by_text(pattern, exact=True),
        ):
            try:
                for index in range(locator.count()):
                    target = locator.nth(index)
                    if target.is_visible():
                        target.click(timeout=5_000)
                        return True
            except Exception:
                continue
        return False

    def _finish_microsoft_login(self, context: Any, original_page: Any, password: str, timeout_ms: int) -> bool:
        deadline = time.monotonic() + min(self.timeout_seconds, timeout_ms / 1000)
        while time.monotonic() < deadline:
            pages = tuple(context.pages)
            auth_pages = [p for p in pages if TruecallerBrowserClient._is_auth_page(p, "microsoft")]
            sync_pages = [p for p in pages if "sync.me" in p.url.lower()]
            if sync_pages and not auth_pages:
                print("Sync.me Microsoft OAuth completed.", file=sys.stderr)
                sync_pages[-1].wait_for_timeout(2_000)
                return True
            transitioned = False
            for auth_page in auth_pages or [original_page]:
                try:
                    body = auth_page.locator("body").inner_text(timeout=2_000).lower()
                    consent = "let this app access your info" in body or "needs your permission" in body
                    if consent and TruecallerBrowserClient._click_microsoft_consent(auth_page):
                        print("Sync.me Microsoft permission detected; accepting...", file=sys.stderr)
                        auth_page.wait_for_timeout(1_000); transitioned = True; break
                    if TruecallerBrowserClient._click_microsoft_text(
                        auth_page, ("other ways to sign in", "diğer oturum açma yöntemleri")
                    ):
                        auth_page.wait_for_timeout(800); transitioned = True; break
                    if TruecallerBrowserClient._click_microsoft_text(
                        auth_page, ("use your password", "parolanızı kullanın")
                    ):
                        auth_page.wait_for_timeout(800)
                        field = auth_page.locator("#i0118, input[name='passwd'], input[type='password']").first
                        field.wait_for(state="visible", timeout=20_000); field.fill(password)
                        try:
                            field.press("Enter")
                        except Exception:
                            pass
                        transitioned = True; break
                    if self._decline_stay_signed_in(auth_page, body):
                        print("Sync.me: declining Microsoft 'Stay signed in?' prompt...", file=sys.stderr)
                        
                        
                        
                        
                        time.sleep(0.9); transitioned = True; break
                except Exception:
                    continue
            if transitioned:
                continue
            time.sleep(0.5)
        return False

    @staticmethod
    def _decline_stay_signed_in(page: Any, body: str = "") -> bool:
        """Decline both legacy and current Microsoft KMSI prompt variants."""
        try:
            url = (page.url or "").lower()
            prompt_visible = (
                "stay signed in" in body
                or "oturumunuz açık kalsın" in body
                or "ppsecure/post.srf" in url
            )
            if not prompt_visible:
                return False
            candidates = (
                page.locator("#idBtn_Back"),
                page.locator("input[type='button'][value='No'], input[type='submit'][value='No']"),
                page.get_by_role("button", name=re.compile(r"^(no|hayır)$", re.I), exact=True),
                page.get_by_text(re.compile(r"^(no|hayır)$", re.I), exact=True),
            )
            for locator in candidates:
                try:
                    for index in range(locator.count()):
                        button = locator.nth(index)
                        if button.is_visible():
                            button.click(timeout=5_000, force=True)
                            return True
                except Exception:
                    continue
        except Exception:
            return False
        return False
