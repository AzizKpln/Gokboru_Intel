from __future__ import annotations

import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class WhatsAppSelfCheckError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WhatsAppSelfCheckResult:
    source: str
    number: str
    status: str
    registered: bool | None
    page_url: str
    message_sent: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WhatsAppSelfCheckClient:
    def __init__(self, analyzer: PhoneAnalyzer, *, timeout_seconds: float = 45.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("WhatsApp timeout must be greater than zero.")
        self.analyzer = analyzer
        self.timeout_seconds = timeout_seconds

    def check_own_number(
        self, raw_number: str, region: str | None = None
    ) -> WhatsAppSelfCheckResult:
        phone = self.analyzer.analyze(raw_number, region)
        if not phone.is_valid:
            raise WhatsAppSelfCheckError("A valid phone number is required.")
        if os.name != "nt" and not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
            raise WhatsAppSelfCheckError(
                "A headed browser requires DISPLAY. Use xvfb-run when running without a desktop."
            )
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise WhatsAppSelfCheckError("Playwright is not installed. Run: bash install.sh") from exc

        digits = re.sub(r"\D", "", phone.e164)
        url = f"https://wa.me/{digits}"
        timeout_ms = max(5_000, int(self.timeout_seconds * 1000))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False,
                args=["--ozone-platform=x11", "--window-size=1100,760"],
            )
            context = browser.new_context(
                viewport={"width": 1100, "height": 760}, locale="en-US"
            )
            try:
                page = context.new_page()
                page.set_default_timeout(min(timeout_ms, 15_000))
                page.goto(url, wait_until="domcontentloaded", timeout=min(timeout_ms, 30_000))
                deadline = time.monotonic() + self.timeout_seconds
                while time.monotonic() < deadline:
                    body = page.locator("body").inner_text(timeout=3_000)
                    status = self._status_from_page(body, page.url)
                    if status:
                        return self._result(phone.e164, status, page.url)
                    page.wait_for_timeout(500)
                return self._result(phone.e164, "inconclusive", page.url)
            finally:
                context.close()
                browser.close()

    @staticmethod
    def _status_from_page(body: str, page_url: str) -> str | None:
        text = " ".join(body.lower().split())
        absent_markers = (
            "phone number shared via url is invalid",
            "phone number isn't on whatsapp",
            "phone number is not on whatsapp",
            "this phone number is not on whatsapp",
            "couldn't find this phone number",
        )
        if any(marker in text for marker in absent_markers):
            return "not_registered"

        
        
        
        active_markers = (
            "continue to chat",
            "chat on whatsapp with",
            "open chat",
        )
        if any(marker in text for marker in active_markers):
            return "registered"

        if "web.whatsapp.com" in page_url.lower() and (
            "log in" in text or "link with phone number" in text or "qr code" in text
        ):
            return "login_required"
        return None

    @staticmethod
    def _result(number: str, status: str, page_url: str) -> WhatsAppSelfCheckResult:
        registered = True if status == "registered" else False if status == "not_registered" else None
        notes = {
            "registered": "WhatsApp's official click-to-chat page accepted the number. Moriarty did not open a conversation or send a message.",
            "not_registered": "WhatsApp reported that the supplied number is invalid or is not on WhatsApp.",
            "login_required": "WhatsApp Web requires a signed-in session, so account presence could not be confirmed.",
            "inconclusive": "WhatsApp did not show a recognizable account-presence result before the timeout.",
        }
        return WhatsAppSelfCheckResult(
            "whatsapp_official_self_check", number, status, registered,
            page_url, False, notes[status],
        )
