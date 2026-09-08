from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class DataBreachLeakCheckError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DataBreachEntry:
    database_name: str
    breach_date: str | None
    exposed_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataBreachLeakCheckResult:
    source: str
    number: str
    status: str
    detection_count: int | None
    breaches: tuple[DataBreachEntry, ...]
    page_url: str
    captcha_detected: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DataBreachLeakCheckClient:
    URL = "https://databreach.com/"

    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        *,
        timeout_seconds: float = 60.0,
        headless: bool = False,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("DataBreach.com timeout must be greater than zero.")
        self.analyzer = analyzer
        self.timeout_seconds = timeout_seconds
        self.headless = headless

    def check_own_number(self, raw_number: str, region: str | None = None) -> DataBreachLeakCheckResult:
        phone = self.analyzer.analyze(raw_number, region)
        if not phone.is_valid:
            raise DataBreachLeakCheckError("A valid phone number is required.")
        if (
            not self.headless
            and os.name != "nt"
            and not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
        ):
            raise DataBreachLeakCheckError(
                "A headed browser requires DISPLAY. Use xvfb-run when running without a desktop."
            )
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise DataBreachLeakCheckError("Playwright is not installed. Run: bash install.sh") from exc

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
            context = browser.new_context(viewport={"width": 1365, "height": 900}, locale="en-US")
            try:
                page = context.new_page()
                page.set_default_timeout(min(timeout_ms, 15_000))
                page.goto(self.URL, wait_until="domcontentloaded", timeout=min(timeout_ms, 30_000))
                page.wait_for_timeout(2_000)
                owner, field = self._find_search_field(page, min(timeout_ms, 20_000))
                print("DataBreach.com search field detected; entering phone number...", file=sys.stderr)
                field.click()
                field.fill("")
                field.press_sequentially(phone.e164, delay=70)
                entered = re.sub(r"\D", "", field.input_value())
                expected = re.sub(r"\D", "", phone.e164)
                if entered != expected:
                    
                    
                    
                    field.fill(phone.e164)
                page.wait_for_timeout(3_000)

                form = field.locator("xpath=ancestor::form[1]")
                button = form.get_by_role("button", name=re.compile(r"^\s*search\s*$", re.I)).first
                if not button.count():
                    button = owner.get_by_role("button", name=re.compile(r"^\s*(search|check)\s*$", re.I)).first
                if not button.count():
                    raise DataBreachLeakCheckError("The Search button was not found.")
                button.wait_for(state="visible", timeout=min(timeout_ms, 10_000))
                print("DataBreach.com phone number entered; clicking Search...", file=sys.stderr)
                button.click(no_wait_after=True)

                deadline = time.monotonic() + self.timeout_seconds
                exposed_seen_at: float | None = None
                while time.monotonic() < deadline:
                    body = page.locator("body").inner_text(timeout=3_000)
                    lowered = " ".join(body.lower().split())
                    if self._captcha_present(page, lowered):
                        return self._result(phone.e164, "manual_action_required", None, (), page.url, True)
                    status = self._result_status(body)
                    if status == "exposed":
                        count = self._detection_count(body)
                        breaches = self._extract_breaches(page)
                        if not breaches:
                            exposed_seen_at = exposed_seen_at or time.monotonic()
                            if time.monotonic() - exposed_seen_at < 8.0:
                                page.wait_for_timeout(500)
                                continue
                        return self._result(phone.e164, status, count, breaches, page.url, False)
                    if status == "not_found":
                        return self._result(phone.e164, status, 0, (), page.url, False)
                    page.wait_for_timeout(500)
                return self._result(phone.e164, "inconclusive", None, (), page.url, False)
            finally:
                context.close()
                browser.close()

    @staticmethod
    def _find_search_field(page: Any, timeout_ms: int) -> tuple[Any, Any]:
        selectors = (
            'input[placeholder*="Email, Name or Phone" i]',
            'input[placeholder*="Email" i][placeholder*="Phone" i]',
            'input[placeholder*="Phone" i]',
            'input[type="search"]',
            'input[type="tel"]',
            'input:not([type]), input[type="text"]',
        )
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            
            
            for frame in page.frames:
                for selector in selectors:
                    candidates = frame.locator(selector)
                    for index in range(candidates.count()):
                        candidate = candidates.nth(index)
                        try:
                            if candidate.is_visible() and candidate.is_editable():
                                return frame, candidate
                        except Exception:
                            continue
            page.wait_for_timeout(250)
        raise DataBreachLeakCheckError(
            "The visible Email, Name or Phone search field was not found."
        )

    @staticmethod
    def _result_status(body: str) -> str | None:
        lines = tuple(" ".join(line.lower().split()) for line in body.splitlines() if line.strip())
        if any(re.fullmatch(r"your data was leaked\s+\d+\s+times?", line) for line in lines):
            return "exposed"
        safe = {
            "no leaks found", "no data breaches found", "your data was not found",
            "good news! your data was not found", "you have not been exposed",
            "no results found", "no results found!",
        }
        if any(line in safe for line in lines) or any(
            re.fullmatch(r"no results found[!.]?", line) for line in lines
        ):
            return "not_found"
        return None

    @staticmethod
    def _detection_count(body: str) -> int | None:
        match = re.search(r"your data was leaked\s+(\d+)\s+times?", body, re.I)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_breaches(page: Any) -> tuple[DataBreachEntry, ...]:
        raw = page.evaluate(r"""
        () => {
          const fieldNames = new Map([
            ['birthday','Birthday'], ['email','Email'], ['name','Name'],
            ['street address','Street Address'], ['social security number','Social Security Number'],
            ['phone','Phone'], ['phone number','Phone'], ['username','Username'],
            ['password','Password'], ['ip address','IP Address'], ['gender','Gender'],
            ['job title','Job Title'], ['employer','Employer'], ['city','City'],
            ['state','State'], ['zip code','ZIP Code'], ['postal code','Postal Code'],
            ['country','Country'], ["driver's license","Driver's License"],
            ['credit card','Credit Card'], ['bank account','Bank Account']
          ]);
          const dateRe = /^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}$/i;
          const visible = el => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 200 && r.height > 45 && s.display !== 'none' && s.visibility !== 'hidden';
          };
          const candidates = [];
          for (const el of document.querySelectorAll('article, li, section, div')) {
            if (!visible(el)) continue;
            const lines = (el.innerText || '').split(/\n+/).map(x => x.trim()).filter(Boolean);
            const date = lines.find(x => dateRe.test(x)) || null;
            const fields = [...new Set(lines.map(x => fieldNames.get(x.toLowerCase())).filter(Boolean))];
            if (!date || !fields.length) continue;
            const names = lines.filter(x =>
              !dateRe.test(x) && !fieldNames.has(x.toLowerCase()) &&
              !/^\+?[\d\s().-]{7,}$/.test(x) && x.length <= 160 &&
              !/^(your data|we found|clear$|search$)/i.test(x)
            );
            if (!names.length) continue;
            const r = el.getBoundingClientRect();
            candidates.push({database_name:names[0], breach_date:date, exposed_fields:fields, area:r.width*r.height});
          }
          const best = new Map();
          for (const item of candidates) {
            const key = item.database_name.toLowerCase() + '|' + item.breach_date;
            if (!best.has(key) || item.area < best.get(key).area) best.set(key, item);
          }
          return [...best.values()].map(({area, ...item}) => item);
        }
        """)
        entries: list[DataBreachEntry] = []
        seen: set[tuple[str, str | None]] = set()
        for item in raw or []:
            name = " ".join(str(item.get("database_name", "")).split()).strip()
            date = " ".join(str(item.get("breach_date", "")).split()).strip() or None
            fields = tuple(dict.fromkeys(
                " ".join(str(value).split()).strip()
                for value in item.get("exposed_fields", []) if str(value).strip()
            ))
            key = (name.casefold(), date)
            if name and fields and key not in seen:
                seen.add(key)
                entries.append(DataBreachEntry(name, date, fields))
        return tuple(entries)

    @staticmethod
    def _captcha_present(page: Any, body: str) -> bool:
        if any(text in body for text in (
            "verify you are human", "confirm you are human", "complete the captcha",
        )):
            return True
        locators = page.locator(
            'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], '
            '[class*="captcha" i], [id*="captcha" i]'
        )
        for index in range(locators.count()):
            try:
                if locators.nth(index).is_visible():
                    return True
            except Exception:
                pass
        return False

    @staticmethod
    def _result(number: str, status: str, count: int | None,
                breaches: tuple[DataBreachEntry, ...], page_url: str,
                captcha: bool) -> DataBreachLeakCheckResult:
        notes = {
            "exposed": "DataBreach.com reported matching exposures. Only breach names, dates, and exposed field categories were collected; leaked values were not accessed.",
            "not_found": "DataBreach.com did not report a matching exposure for the supplied number.",
            "manual_action_required": "DataBreach.com requested human verification; Moriarty did not bypass it.",
            "inconclusive": "DataBreach.com did not show a recognizable result before the timeout.",
        }
        return DataBreachLeakCheckResult(
            "databreach_phone_leak_check", number, status, count, breaches,
            page_url, captcha, notes[status],
        )
