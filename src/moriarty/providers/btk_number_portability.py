from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class BTKNumberPortabilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BTKNumberPortabilityResult:
    source: str
    number: str
    status: str
    current_operator: str | None
    number_ported: bool | None
    page_url: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BTKNumberPortabilityClient:
    URL = "https://www.turkiye.gov.tr/btk-numara-tasima?submit=&theme=default"
    OPERATORS = ("Turkcell", "Vodafone", "Türk Telekom", "Turk Telekom", "TT Mobil")

    def __init__(self, analyzer: PhoneAnalyzer, *, timeout_seconds: float = 90.0, headless: bool = False) -> None:
        self.analyzer = analyzer
        self.timeout_seconds = timeout_seconds
        self.headless = headless

    def check(self, raw_number: str, region: str | None = None) -> BTKNumberPortabilityResult:
        phone = self.analyzer.analyze(raw_number, region)
        if not phone.is_valid:
            raise BTKNumberPortabilityError("A valid phone number is required.")
        if phone.region_code != "TR":
            return BTKNumberPortabilityResult("btk_number_portability", phone.e164, "unsupported_country", None, None, self.URL, "BTK number-portability lookup supports Turkish numbers only.")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BTKNumberPortabilityError("Playwright is required for BTK lookup.") from exc
        timeout_ms = int(self.timeout_seconds * 1000)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=self.headless,
                args=["--ozone-platform=x11"] if os.name != "nt" else [],
            )
            page = browser.new_page(locale="tr-TR")
            try:
                page.goto(self.URL, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(1500)
                field = page.locator("input[type='tel'], input[name*='telefon' i], input[id*='telefon' i]").first
                if field.count() == 0:
                    return BTKNumberPortabilityResult("btk_number_portability", phone.e164, "manual_action_required", None, None, page.url, "The official service requires login, CAPTCHA, or its form layout changed.")
                field.fill(re.sub(r"\D", "", phone.e164)[2:])
                button = page.get_by_role("button", name=re.compile(r"sorgula|devam|gönder", re.I)).first
                if button.count() == 0:
                    button = page.locator("input[type='submit']").first
                button.click(timeout=timeout_ms)
                page.wait_for_timeout(2500)
                text = page.locator("body").inner_text(timeout=timeout_ms)
                return self.parse_result(phone.e164, page.url, text)
            finally:
                browser.close()

    @classmethod
    def parse_result(cls, number: str, page_url: str, text: str) -> BTKNumberPortabilityResult:
        normalized = " ".join(text.split())
        operator = next((name for name in cls.OPERATORS if name.casefold() in normalized.casefold()), None)
        if operator:
            ported = None
            if re.search(r"taşınmış|taşınmıştır", normalized, re.I):
                ported = True
            elif re.search(r"taşınmamış|taşınmamıştır", normalized, re.I):
                ported = False
            return BTKNumberPortabilityResult("btk_number_portability", number, "found", operator, ported, page_url, "Operator information was read from the official BTK/e-Devlet service.")
        if re.search(r"captcha|güvenlik kodu|giriş yap|kimliğimi şimdi doğrula", normalized, re.I):
            status = "manual_action_required"
        elif re.search(r"geçerli.*numara|sonuç bulunamadı|kayıt bulunamadı", normalized, re.I):
            status = "not_found"
        else:
            status = "page_changed"
        return BTKNumberPortabilityResult("btk_number_portability", number, status, None, None, page_url, "No operator result could be parsed; the service may require manual verification.")
