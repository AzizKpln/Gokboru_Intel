from __future__ import annotations

import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class CybernewsLeakCheckError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CybernewsLeakCheckResult:
    source: str
    number: str
    status: str
    breach_count: int | None
    detection_count: int | None
    databases: tuple[str, ...]
    page_url: str
    captcha_detected: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CybernewsLeakCheckClient:
    URL = "https://cybernews.com/personal-data-leak-check/"

    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        *,
        timeout_seconds: float = 60.0,
        headless: bool = False,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Cybernews timeout must be greater than zero.")
        self.analyzer = analyzer
        self.timeout_seconds = timeout_seconds
        self.headless = headless

    def check_own_number(
        self, raw_number: str, region: str | None = None
    ) -> CybernewsLeakCheckResult:
        phone = self.analyzer.analyze(raw_number, region)
        if not phone.is_valid:
            raise CybernewsLeakCheckError("A valid phone number is required.")
        if (
            not self.headless
            and os.name != "nt"
            and not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
        ):
            raise CybernewsLeakCheckError(
                "A headed browser requires DISPLAY. Use xvfb-run for an invisible virtual display."
            )
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise CybernewsLeakCheckError("Playwright is not installed. Run: bash install.sh") from exc

        timeout_ms = max(5_000, int(self.timeout_seconds * 1000))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=self.headless,
                args=(
                    ["--window-size=1365,900"]
                    if self.headless
                    else ["--ozone-platform=x11", "--window-size=1365,900"]
                ),
            )
            context = browser.new_context(
                viewport={"width": 1365, "height": 900}, locale="en-US"
            )
            try:
                page = context.new_page()
                page.set_default_timeout(min(timeout_ms, 15_000))
                page.goto(
                    self.URL,
                    wait_until="domcontentloaded",
                    timeout=min(timeout_ms, 30_000),
                )
                field = page.locator(
                    'input[placeholder*="Email or Phone" i], '
                    'input[placeholder*="phone" i], input[type="tel"]'
                ).first
                field.wait_for(state="visible", timeout=min(timeout_ms, 20_000))
                field.fill(phone.e164)
                
                
                page.wait_for_timeout(3_000)
                form = field.locator("xpath=ancestor::form[1]")
                button = form.get_by_role(
                    "button", name=re.compile(r"check\s*now", re.I)
                ).first
                if not button.count():
                    button = field.locator(
                        'xpath=ancestor::*[.//button[contains('
                        'translate(normalize-space(.), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", '
                        '"abcdefghijklmnopqrstuvwxyz"), "check now")]][1]//button'
                    ).first
                if not button.count():
                    raise CybernewsLeakCheckError(
                        "The Check now button next to the phone field was not found."
                    )
                button.click(timeout=min(timeout_ms, 10_000), no_wait_after=True)

                deadline = time.monotonic() + self.timeout_seconds
                stable_result = None
                stable_since = time.monotonic()
                last_exposed = None
                while time.monotonic() < deadline:
                    body = page.locator("body").inner_text(timeout=3_000)
                    lowered = " ".join(body.lower().split())
                    if self._captcha_present(page, lowered):
                        return CybernewsLeakCheckResult(
                            "cybernews_personal_data_leak_check",
                            phone.e164,
                            "manual_action_required",
                            None,
                            None,
                            (),
                            page.url,
                            True,
                            "Cybernews requested a CAPTCHA or human verification; Moriarty did not bypass it.",
                        )
                    status = self._result_status(body)
                    if status:
                        databases = self._database_names(body) if status == "exposed" else ()
                        detection_count = self._detection_count(body) if status == "exposed" else None
                        if status == "exposed":
                            last_exposed = (databases, detection_count, self._breach_count(body))
                        signature = (status, databases, detection_count, self._breach_count(body))
                        if signature != stable_result:
                            stable_result = signature
                            stable_since = time.monotonic()
                        if (status == "exposed" and not databases and detection_count is None) or time.monotonic() - stable_since < 2.0:
                            page.wait_for_timeout(500)
                            continue
                        return CybernewsLeakCheckResult(
                            "cybernews_personal_data_leak_check",
                            phone.e164,
                            status,
                            len(databases) if databases else self._breach_count(body),
                            detection_count,
                            databases,
                            page.url,
                            False,
                            (
                                "Cybernews reported that the number appears in its leak-check results. No leaked credentials were collected."
                                if status == "exposed"
                                else "Cybernews did not report a matching exposure for the supplied number."
                            ),
                        )
                    stable_result = None
                    page.wait_for_timeout(500)
                if last_exposed is not None:
                    databases, detection_count, breach_count = last_exposed
                    return CybernewsLeakCheckResult(
                        "cybernews_personal_data_leak_check", phone.e164, "exposed",
                        len(databases) if databases else breach_count, detection_count,
                        databases, page.url, False,
                        "Exposure was reported, but the detail loading deadline expired. Missing details are unknown, not zero.",
                    )
                return CybernewsLeakCheckResult(
                    "cybernews_personal_data_leak_check",
                    phone.e164,
                    "inconclusive",
                    None,
                    None,
                    (),
                    page.url,
                    False,
                    "Cybernews did not show a recognizable result before the timeout.",
                )
            finally:
                context.close()
                browser.close()

    @staticmethod
    def _captcha_present(page: Any, body: str) -> bool:
        
        
        
        if any(value in body for value in (
            "verify you are human",
            "confirm you are human",
            "complete the captcha",
            "checking your browser before accessing",
        )):
            return True
        challenges = page.locator(
            'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], '
            'iframe[src*="turnstile"], [class*="captcha" i], '
            '[id*="captcha" i]'
        )
        for index in range(challenges.count()):
            try:
                if challenges.nth(index).is_visible():
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _result_status(body: str) -> str | None:
        
        
        
        lines = tuple(
            " ".join(line.lower().split())
            for line in body.splitlines()
            if line.strip()
        )
        safe_exact = {
            "you are safe for now",
            "safe for now",
            "no breaches found",
            "no breach found",
            "good news! no breaches found",
        }
        if any(line in safe_exact for line in lines):
            return "not_found"
        exposed_exact = {
            "your data has been leaked",
            "your data was leaked",
            "data leak detected",
            "leaks found",
        }
        if any(line in exposed_exact for line in lines):
            return "exposed"
        if any(
            re.fullmatch(r"(?:your data was )?found in (?:a|\d+) data breaches?", line)
            or re.fullmatch(r"\d+ breached accounts? found", line)
            for line in lines
        ):
            return "exposed"
        return None

    @staticmethod
    def _breach_count(body: str) -> int | None:
        for pattern in (
            r"found\s+in\s+(\d+)\s+(?:data\s+)?breach",
            r"(\d+)\s+(?:data\s+)?breach(?:es)?\s+found",
        ):
            match = re.search(pattern, body, re.I)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _detection_count(body: str) -> int | None:
        match = re.search(
            r"(?:it\s+)?was\s+detected\s+(\d+)\s+times?\s+in\s+leaked\s+databases?",
            body,
            re.I,
        )
        return int(match.group(1)) if match else None

    @staticmethod
    def _database_names(body: str) -> tuple[str, ...]:
        match = re.search(
            r"your\s+personal\s+data\s+was\s+found\s+in\s+the\s+following\s+data\s+leaks?\s*:\s*"
            r"(.+?)\s+(?:it\s+)?was\s+detected\s+\d+\s+times?\s+in\s+leaked\s+databases?",
            body,
            re.I | re.S,
        )
        if not match:
            return ()
        names: list[str] = []
        seen: set[str] = set()
        for raw_name in match.group(1).split(","):
            name = " ".join(raw_name.split()).strip(" .;:\t\r\n")
            key = name.casefold()
            if name and key not in seen:
                seen.add(key)
                names.append(name)
        return tuple(names)
