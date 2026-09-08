from __future__ import annotations

from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import phonenumbers

from moriarty.domain.models import BusinessListing, BusinessListingsResult
from moriarty.services.phone_analyzer import PhoneAnalyzer

_BASE_URL = "https://gotmynumber.co.uk"
_VERIFIED_TEXT = "A verified UK business on the Towpath identity network."


class GotMyNumberBusinessClient:
    name = "got_my_number_uk"

    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 15.0, loader=None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Source timeout must be greater than zero.")
        self._analyzer, self._timeout = analyzer, timeout_seconds
        self._loader = loader or _load

    def lookup(self, raw_number: str, default_region: str | None = None) -> BusinessListingsResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        parsed = phonenumbers.parse(phone.e164, None)
        if phonenumbers.region_code_for_number(parsed) != "GB":
            return BusinessListingsResult(self.name, phone.e164, ())
        url = _BASE_URL + "/number/" + quote(phone.e164, safe="+")
        parser = _ResultParser(); parser.feed(self._loader(url, self._timeout))
        name = _verified_business_name(parser.paragraphs)
        listings = () if name is None else (BusinessListing(
            name=name,
            category="verified UK business",
            address=None,
            latitude=None,
            longitude=None,
            phone=phone.e164,
            website=None,
            source_url=url,
        ),)
        return BusinessListingsResult(self.name, phone.e164, listings)


def _load(url: str, timeout: float) -> str:
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; Moriarty-V5/0.1; public business lookup)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"GotMyNumber returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"GotMyNumber network error: {exc.reason}") from exc


def _verified_business_name(paragraphs: tuple[str, ...]) -> str | None:
    if not any(_VERIFIED_TEXT in text for text in paragraphs):
        return None
    for text in paragraphs:
        if text.startswith("Registered to "):
            name = text.removeprefix("Registered to ").strip()
            if name and name.lower() != "a uk business":
                return name
    return None


class _ResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: tuple[str, ...] = ()
        self._depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "p":
            if self._depth == 0: self._parts = []
            self._depth += 1

    def handle_data(self, data: str) -> None:
        if self._depth and data.strip(): self._parts.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._depth:
            self._depth -= 1
            if self._depth == 0:
                text = " ".join(self._parts).strip()
                if text: self.paragraphs += (text,)
