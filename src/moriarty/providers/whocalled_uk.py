from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import phonenumbers

from moriarty.domain.models import LookupStatus, ReputationResult
from moriarty.services.phone_analyzer import PhoneAnalyzer


class ReputationSourceError(RuntimeError):
    """Raised when a reputation source cannot be queried safely."""


@dataclass(frozen=True, slots=True)
class PageResponse:
    status: int
    body: str


class WhoCalledUkClient:
    name = "whocalled_uk"

    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        timeout_seconds: float = 8.0,
        loader=None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Source timeout must be greater than zero.")
        self._analyzer = analyzer
        self._timeout_seconds = timeout_seconds
        self._loader = loader or _load_page

    def lookup(
        self, raw_number: str, default_region: str | None = None
    ) -> ReputationResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        if phone.region_code != "GB":
            return ReputationResult(
                source=self.name,
                status=LookupStatus.NOT_APPLICABLE,
                number=phone.e164,
                url=None,
            )

        parsed = phonenumbers.parse(phone.e164, None)
        national = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.NATIONAL
        )
        national_digits = "".join(character for character in national if character.isdigit())
        url = f"https://whocalled.co.uk/phone/{national_digits}"
        response = self._loader(url, self._timeout_seconds)
        if response.status == 404:
            return ReputationResult(
                source=self.name,
                status=LookupStatus.NOT_FOUND,
                number=phone.e164,
                url=url,
            )
        if response.status != 200:
            raise ReputationSourceError(
                f"WhoCalled UK returned HTTP {response.status}."
            )
        return _parse_page(response.body, phone.e164, url)


def _load_page(url: str, timeout: float) -> PageResponse:
    request = Request(
        url,
        headers={
            "User-Agent": "Moriarty-V5/0.1 (+public phone reputation lookup)",
            "Accept": "text/html",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return PageResponse(
                status=response.status,
                body=response.read().decode(charset, errors="replace"),
            )
    except HTTPError as exc:
        if exc.code == 404:
            return PageResponse(status=404, body="")
        raise ReputationSourceError(f"WhoCalled UK returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise ReputationSourceError(f"WhoCalled UK network error: {exc.reason}") from exc


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    @property
    def text(self) -> str:
        return " ".join(self.parts)


def _parse_page(body: str, e164: str, url: str) -> ReputationResult:
    parser = _TextExtractor()
    parser.feed(body)
    text = parser.text
    if "Who called me from" not in text:
        return ReputationResult(
            source=WhoCalledUkClient.name,
            status=LookupStatus.NOT_FOUND,
            number=e164,
            url=url,
        )

    security_level = _first_group(
        r"Security Level\s+(Dangerous|Harassing|Unknown|Neutral|Safe)\b", text
    )
    report_count = _first_int(r"phone number\s+(\d+)\s+times\b", text)
    lookup_count = _first_int(r"checked\s+(\d+)\s+times\b", text)
    carrier = _first_group(r"carrier name is\s+(.+?),\s+mobile country code", text)
    line_type = _first_group(r"phone type is\s+(.+?)\.", text)
    area_name = _first_group(r"Area Name\s+(.+?)\s+Area Code", text)
    category_text = _first_group(
        r"reported\s+.+?\s+in these categories\s+(.+?)\.", text
    )
    categories: dict[str, int] = {}
    if category_text:
        for name, count in re.findall(r"([A-Za-z][A-Za-z ]*?)\s+\((\d+)\s+times\)", category_text):
            categories[name.strip()] = int(count)

    return ReputationResult(
        source=WhoCalledUkClient.name,
        status=LookupStatus.FOUND,
        number=e164,
        url=url,
        security_level=security_level,
        report_count=report_count,
        lookup_count=lookup_count,
        categories=categories,
        carrier=carrier,
        line_type=line_type,
        area_name=area_name,
    )


def _first_group(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _first_int(pattern: str, text: str) -> int | None:
    value = _first_group(pattern, text)
    return int(value) if value is not None else None
