from __future__ import annotations

from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

import phonenumbers

from moriarty.domain.models import BusinessListing, BusinessListingsResult
from moriarty.services.phone_analyzer import PhoneAnalyzer

_BASE_URL = "https://firmafihristi.com.tr"


class FirmaFihristiBusinessClient:
    name = "firma_fihristi_tr"

    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 15.0, loader=None, max_results: int = 20) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Source timeout must be greater than zero.")
        if max_results <= 0:
            raise ValueError("Maximum results must be greater than zero.")
        self._analyzer, self._timeout = analyzer, timeout_seconds
        self._loader, self._max_results = loader or _load, max_results

    def lookup(self, raw_number: str, default_region: str | None = None) -> BusinessListingsResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        parsed = phonenumbers.parse(phone.e164, None)
        if phonenumbers.region_code_for_number(parsed) != "TR":
            return BusinessListingsResult(self.name, phone.e164, ())
        national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL).replace("(", "").replace(")", "")
        url = _BASE_URL + "/ara?" + urlencode({"q": national})
        parser = _SearchTableParser()
        parser.feed(self._loader(url, self._timeout))
        expected = _digits(phone.e164)
        listings = tuple(
            listing for listing in (_listing(row) for row in parser.rows)
            if listing is not None and _tr_e164_digits(listing.phone) == expected
        )[: self._max_results]
        return BusinessListingsResult(self.name, phone.e164, listings)


def _load(url: str, timeout: float) -> str:
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; Moriarty-V5/0.1; public business lookup)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.7",
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            try:
                return payload.decode("utf-8")
            except UnicodeDecodeError:
                return payload.decode("windows-1254", errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Firma Fihristi returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"Firma Fihristi network error: {exc.reason}") from exc


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _tr_e164_digits(value: str) -> str:
    digits = _digits(value)
    if len(digits) == 11 and digits.startswith("0"):
        return "90" + digits[1:]
    if len(digits) == 10:
        return "90" + digits
    return digits


def _listing(row: list[dict[str, str]]) -> BusinessListing | None:
    if len(row) < 5:
        return None
    name, center, category, location, phone = (cell.get("text", "").strip() for cell in row[:5])
    source_path = row[0].get("href", "")
    if not name or not phone or not source_path.startswith("/firma/"):
        return None
    address = ", ".join(part for part in (location, center) if part) or None
    return BusinessListing(
        name=name,
        category=category or None,
        address=address,
        latitude=None,
        longitude=None,
        phone=phone,
        website=None,
        source_url=urljoin(_BASE_URL, source_path),
    )


class _SearchTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, str]]] = []
        self._in_body = False
        self._row: list[dict[str, str]] | None = None
        self._cell: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "tbody":
            self._in_body = True
        elif self._in_body and tag == "tr":
            self._row = []
        elif self._row is not None and tag == "td":
            self._cell = {"text": "", "href": ""}
        elif self._cell is not None and tag == "a":
            href = values.get("href") or ""
            if href.startswith("/firma/"):
                self._cell["href"] = href

    def handle_data(self, data: str) -> None:
        if self._cell is not None and data.strip():
            self._cell["text"] = (self._cell["text"] + " " + data.strip()).strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row.append(self._cell); self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "tbody":
            self._in_body = False
