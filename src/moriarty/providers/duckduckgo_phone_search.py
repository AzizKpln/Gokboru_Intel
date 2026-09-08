from __future__ import annotations

import html
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any, Callable

from moriarty.services.phone_analyzer import PhoneAnalyzer


class DuckDuckGoPhoneSearchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DuckDuckGoPhoneMatch:
    title: str
    url: str
    domain: str
    snippet: str
    matched_variant: str


@dataclass(frozen=True, slots=True)
class DuckDuckGoPhoneSearchResult:
    source: str
    number: str
    status: str
    total_matches: int
    variants_searched: tuple[str, ...]
    matches: tuple[DuckDuckGoPhoneMatch, ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _ResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._depth = 0
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if self._current is None and "result" in classes:
            self._current = {"title": "", "url": "", "snippet": ""}
            self._depth = 1
        elif self._current is not None:
            self._depth += 1
        if self._current is None:
            return
        if tag == "a" and "result__a" in classes:
            self._capture = "title"
            self._current["url"] = values.get("href", "")
        elif "result__snippet" in classes:
            self._capture = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        self._depth -= 1
        if tag in {"a", "div"}:
            self._capture = None
        if self._depth == 0:
            self.results.append(self._current)
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._capture:
            self._current[self._capture] += " " + data


class DuckDuckGoPhoneSearchClient:
    URL = "https://html.duckduckgo.com/html/"

    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        *,
        max_results: int = 20,
        timeout_seconds: float = 30.0,
        loader: Callable[[urllib.request.Request, float], str] | None = None,
        browser_fallback: bool = True,
        headless: bool = False,
    ) -> None:
        if not 1 <= max_results <= 50:
            raise ValueError("DuckDuckGo result limit must be between 1 and 50.")
        self.analyzer = analyzer
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds
        self.loader = loader or self._load
        self.browser_fallback = browser_fallback
        self.headless = headless

    def search(self, raw_number: str, region: str | None = None) -> DuckDuckGoPhoneSearchResult:
        phone = self.analyzer.analyze(raw_number, region)
        if not phone.is_valid:
            raise DuckDuckGoPhoneSearchError("A valid phone number is required.")
        variants = tuple(dict.fromkeys(
            item for item in (phone.e164, phone.e164.lstrip("+"), phone.international_format, phone.national_format) if item
        ))
        query = " ".join(f'"{item}"' for item in variants)
        params = urllib.parse.urlencode({"q": query, "kl": "tr-tr" if phone.region_code == "TR" else "wt-wt", "kp": "1"})
        request = urllib.request.Request(
            f"{self.URL}?{params}",
            headers={"User-Agent": "Mozilla/5.0 (Moriarty-V5; public self-audit)", "Accept": "text/html"},
        )
        try:
            document = self.loader(request, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            if self.browser_fallback and exc.code in {403, 418, 429, 503}:
                return self._browser_search(phone.e164, variants, query, phone.region_code)
            status = "rate_limited" if exc.code == 429 else "access_blocked" if exc.code in {403, 418} else "provider_error"
            return self._result(phone.e164, status, variants, (), f"DuckDuckGo returned HTTP {exc.code}.")
        except urllib.error.URLError as exc:
            if self.browser_fallback:
                return self._browser_search(phone.e164, variants, query, phone.region_code)
            raise DuckDuckGoPhoneSearchError(f"DuckDuckGo request failed: {exc.reason}") from exc
        except (ConnectionResetError, TimeoutError, OSError) as exc:
            if self.browser_fallback:
                return self._browser_search(phone.e164, variants, query, phone.region_code)
            raise DuckDuckGoPhoneSearchError(f"DuckDuckGo request failed: {exc}") from exc
        if re.search(r"captcha|anomaly|automated quer|verify.*human", document, re.I):
            if self.browser_fallback:
                return self._browser_search(phone.e164, variants, query, phone.region_code)
            return self._result(phone.e164, "access_blocked", variants, (), "DuckDuckGo requested human verification or blocked the search.")
        parser = _ResultsParser()
        parser.feed(document)
        matches = self._filter_items(phone.e164, variants, parser.results)
        return self._result(
            phone.e164, "found" if matches else "not_found", variants, matches,
            "Only exact public-search result metadata was retained; a match does not establish ownership.",
        )

    def _browser_search(self, number: str, variants: tuple[str, ...], query: str, region_code: str | None) -> DuckDuckGoPhoneSearchResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise DuckDuckGoPhoneSearchError("Playwright is required for DuckDuckGo browser fallback.") from exc
        timeout_ms = int(self.timeout_seconds * 1000)
        params = urllib.parse.urlencode({"q": query, "kl": "tr-tr" if region_code == "TR" else "wt-wt", "kp": "1"})
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=self.headless,
                args=["--ozone-platform=x11"] if os.name != "nt" else [],
            )
            page = browser.new_page(locale="tr-TR" if region_code == "TR" else "en-US", viewport={"width": 1440, "height": 1000})
            try:
                page.goto(f"https://duckduckgo.com/?{params}", wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2500)
                body = page.locator("body").inner_text(timeout=timeout_ms)
                if re.search(r"captcha|anomaly|automated quer|verify.*human", body, re.I):
                    return self._result(number, "access_blocked", variants, (), "DuckDuckGo requested human verification in the browser.")
                items = page.locator("[data-testid='result'], article").evaluate_all(
                    """nodes => nodes.map(node => {
                        const link = node.querySelector('[data-testid="result-title-a"], h2 a');
                        const snippet = node.querySelector('[data-testid="result-snippet"], [data-result="snippet"], .result__snippet');
                        return {title: link?.innerText || '', url: link?.href || '', snippet: snippet?.innerText || ''};
                    })"""
                )
                matches = self._filter_items(number, variants, items if isinstance(items, list) else [])
                return self._result(
                    number, "found" if matches else "not_found", variants, matches,
                    "DuckDuckGo browser fallback retained only exact public-result metadata.",
                )
            except Exception as exc:
                raise DuckDuckGoPhoneSearchError(f"DuckDuckGo browser fallback failed: {exc}") from exc
            finally:
                browser.close()

    def _filter_items(self, number: str, variants: tuple[str, ...], items: list[dict[str, str]]) -> tuple[DuckDuckGoPhoneMatch, ...]:
        target_digits = re.sub(r"\D", "", number)
        matches: list[DuckDuckGoPhoneMatch] = []
        seen: set[str] = set()
        for item in items:
            title = " ".join(html.unescape(item["title"]).split())[:300]
            snippet = " ".join(html.unescape(item["snippet"]).split())[:500]
            url = self._direct_url(html.unescape(item["url"]).strip())
            visible = f"{title} {snippet} {url}"
            if not url or url in seen or target_digits not in re.sub(r"\D", "", visible):
                continue
            seen.add(url)
            matched = next((variant for variant in variants if variant in visible), number)
            matches.append(DuckDuckGoPhoneMatch(title or "Untitled", url, urllib.parse.urlparse(url).netloc, snippet, matched))
            if len(matches) >= self.max_results:
                break
        return tuple(matches)

    @staticmethod
    def _direct_url(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        return query.get("uddg", [url])[0] if "uddg" in query else url

    @staticmethod
    def _load(request: urllib.request.Request, timeout: float) -> str:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")

    @staticmethod
    def _result(number: str, status: str, variants: tuple[str, ...], matches: tuple[DuckDuckGoPhoneMatch, ...], note: str) -> DuckDuckGoPhoneSearchResult:
        return DuckDuckGoPhoneSearchResult("duckduckgo_public_phone_search", number, status, len(matches), variants, matches, note)
