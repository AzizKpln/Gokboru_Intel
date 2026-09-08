from __future__ import annotations

from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import phonenumbers

from moriarty.domain.models import BusinessListing, BusinessListingsResult
from moriarty.services.phone_analyzer import PhoneAnalyzer

_BASE_URL = "https://www.dasoertliche.de"


class DasOertlicheBusinessClient:
    name = "das_oertliche_de"

    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 15.0, loader=None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Source timeout must be greater than zero.")
        self._analyzer, self._timeout = analyzer, timeout_seconds
        self._loader = loader or _load

    def lookup(self, raw_number: str, default_region: str | None = None) -> BusinessListingsResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        parsed = phonenumbers.parse(phone.e164, None)
        if phonenumbers.region_code_for_number(parsed) != "DE":
            return BusinessListingsResult(self.name, phone.e164, ())
        national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
        search_url = _BASE_URL + "/rueckwaertssuche/?" + urlencode({"ph":national})
        final_url, html = self._loader(search_url, self._timeout)
        parser = _DetailParser(); parser.feed(html)
        exact_phone = next((value for value in parser.phones if _normalizes_to(value, phone.e164, self._analyzer)), None)
        if not parser.is_organization or not parser.name or not exact_phone:
            return BusinessListingsResult(self.name, phone.e164, ())
        source_url = parser.canonical or final_url
        listing = BusinessListing(
            name=parser.name,
            category="business directory entry",
            address=_clean_address(parser.address_parts),
            latitude=None,
            longitude=None,
            phone=exact_phone,
            website=parser.website,
            source_url=source_url,
        )
        return BusinessListingsResult(self.name, phone.e164, (listing,))


def _load(url: str, timeout: float) -> tuple[str, str]:
    request = Request(url, headers={
        "User-Agent":"Mozilla/5.0 (compatible; Moriarty-V5/0.1; public business lookup)",
        "Accept":"text/html,application/xhtml+xml", "Accept-Language":"de-DE,de;q=0.9,en;q=0.7",
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.geturl(), response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Das Örtliche returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"Das Örtliche network error: {exc.reason}") from exc


def _normalizes_to(value: str, expected: str, analyzer: PhoneAnalyzer) -> bool:
    try:
        return analyzer.analyze(value, "DE").e164 == expected
    except Exception:
        return False


def _clean_address(parts: list[str]) -> str | None:
    text = " ".join(" ".join(parts).split())
    for label in ("Zum Kartenausschnitt", "Routenplaner"):
        text = text.replace(label, "")
    text = " ".join(text.split())
    return text or None


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.name: str | None = None; self.canonical: str | None = None
        self.website: str | None = None; self.phones: list[str] = []
        self.address_parts: list[str] = []; self.is_organization = False
        self._in_h1 = False; self._address_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs); classes = set((values.get("class") or "").split())
        if tag == "link" and (values.get("rel") or "").lower() == "canonical": self.canonical = values.get("href")
        if values.get("itemtype") == "https://schema.org/Organization": self.is_organization = True
        if tag == "h1": self._in_h1 = True
        if tag == "div" and "det_address" in classes: self._address_depth = 1
        elif self._address_depth and tag == "div": self._address_depth += 1
        if tag == "a":
            href = values.get("href") or ""
            if href.lower().startswith("tel:"): self.phones.append(href[4:])
            if "det_website" in classes and href.startswith(("http://","https://")): self.website = href

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if self._in_h1 and value: self.name = (self.name + " " + value).strip() if self.name else value
        if self._address_depth and value: self.address_parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1": self._in_h1 = False
        if tag == "div" and self._address_depth: self._address_depth -= 1
