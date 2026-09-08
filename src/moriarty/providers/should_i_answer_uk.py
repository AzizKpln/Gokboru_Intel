from __future__ import annotations

import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import phonenumbers

from moriarty.domain.models import LookupStatus, ReputationResult
from moriarty.providers.whocalled_uk import PageResponse, ReputationSourceError, _TextExtractor
from moriarty.services.phone_analyzer import PhoneAnalyzer


class ShouldIAnswerUkClient:
    name = "should_i_answer_uk"

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
        url = f"https://www.shouldianswer.co.uk/phone-number/{national_digits}"
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
                f"Should I Answer UK returned HTTP {response.status}."
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
        raise ReputationSourceError(
            f"Should I Answer UK returned HTTP {exc.code}."
        ) from exc
    except URLError as exc:
        raise ReputationSourceError(
            f"Should I Answer UK network error: {exc.reason}"
        ) from exc


def _parse_page(body: str, e164: str, url: str) -> ReputationResult:
    parser = _TextExtractor()
    parser.feed(body)
    text = parser.text
    if "Who called you from" not in text:
        return ReputationResult(
            source=ShouldIAnswerUkClient.name,
            status=LookupStatus.NOT_FOUND,
            number=e164,
            url=url,
        )

    rating_match = re.search(
        r"has\s+(positive|negative|neutral)\s+rating", text, re.IGNORECASE
    )
    security_level = rating_match.group(1).title() if rating_match else None
    rating_counts: dict[str, int] = {}
    for count, rating in re.findall(
        r"(\d+)\s+users?(?:\s+rated\s+it)?\s+as\s+"
        r"(positive|negative|neutral)",
        text,
        re.IGNORECASE,
    ):
        rating_counts[rating.title()] = int(count)
    single_rating = re.search(
        r"single user\s+as\s+(positive|negative|neutral)", text, re.IGNORECASE
    )
    if single_rating:
        rating_counts[single_rating.group(1).title()] = 1

    category_match = re.search(
        r"mostly categorized as\s+(.+?)\.\s+Th(?:is|ese) ratings",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    categories: dict[str, int] = {}
    if category_match:
        for name, count in re.findall(
            r"([A-Za-z][A-Za-z ]*?)\s+\((\d+)\s+times\)",
            category_match.group(1),
        ):
            clean_name = re.sub(r"^(?:and\s+)", "", name.strip(), flags=re.I)
            categories[clean_name] = int(count)

    area_match = re.search(
        r"United Kingdom(?:,\s*([A-Za-z][A-Za-z ]+?))?\s+Phone number",
        text,
        re.IGNORECASE,
    )
    return ReputationResult(
        source=ShouldIAnswerUkClient.name,
        status=LookupStatus.FOUND,
        number=e164,
        url=url,
        security_level=security_level,
        report_count=sum(rating_counts.values()) or None,
        categories={**categories, **{f"Rating: {key}": value for key, value in rating_counts.items()}},
        area_name=area_match.group(1).strip() if area_match and area_match.group(1) else None,
    )
