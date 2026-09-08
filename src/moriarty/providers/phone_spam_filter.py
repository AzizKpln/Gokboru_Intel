from __future__ import annotations

import html
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import phonenumbers

from moriarty.domain.models import LookupStatus, ReputationResult
from moriarty.providers.whocalled_uk import PageResponse, ReputationSourceError
from moriarty.services.phone_analyzer import PhoneAnalyzer

_HOSTS = {
    "AU": "au.phonespamfilter.com",
    "FR": "www.phonespamfilter.fr",
    "GB": "www.phonespamfilter.co.uk",
    "NZ": "www.phonespamfilter.co.nz",
    "US": "www.phonespamfilter.com",
}


class PhoneSpamFilterClient:
    name = "phone_spam_filter"

    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 8.0, loader=None, max_comments: int = 10) -> None:
        if timeout_seconds <= 0: raise ValueError("Source timeout must be greater than zero.")
        if max_comments < 0: raise ValueError("Maximum comments cannot be negative.")
        self._analyzer, self._timeout_seconds = analyzer, timeout_seconds
        self._loader, self._max_comments = loader or _load_page, max_comments

    def lookup(self, raw_number: str, default_region: str | None = None) -> ReputationResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        host = _HOSTS.get(phone.region_code or "")
        if not host:
            return ReputationResult(self.name, LookupStatus.NOT_APPLICABLE, phone.e164, None)
        parsed = phonenumbers.parse(phone.e164, None)
        national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
        digits = "".join(character for character in national if character.isdigit())
        url = f"https://{host}/{digits}"
        response = self._loader(url, self._timeout_seconds)
        if response.status == 404: return ReputationResult(self.name, LookupStatus.NOT_FOUND, phone.e164, url)
        if response.status != 200: raise ReputationSourceError(f"Phone Spam Filter returned HTTP {response.status}.")
        return _parse_page(response.body, phone.e164, url, self._max_comments)


def _load_page(url: str, timeout: float) -> PageResponse:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-GB,en;q=0.9"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return PageResponse(response.status, response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
    except HTTPError as exc:
        if exc.code == 404: return PageResponse(404, "")
        raise ReputationSourceError(f"Phone Spam Filter returned HTTP {exc.code}.") from exc
    except URLError as exc: raise ReputationSourceError(f"Phone Spam Filter network error: {exc.reason}") from exc


def _parse_page(body: str, e164: str, url: str, max_comments: int) -> ReputationResult:
    section = re.search(r'<div\s+class=["\']complaint-posts["\']>(.*?)(?:</div>\s*</div>|</section>)', body, re.I | re.S)
    content = section.group(1) if section else ""
    if re.search(r"No complaints found", content, re.I) or not content:
        return ReputationResult(PhoneSpamFilterClient.name, LookupStatus.NOT_FOUND, e164, url)
    count = re.search(r"([\d,]+)\s+complaints?", content, re.I)
    fragments = re.findall(r"<li[^>]*>(.*?)</li>", content, re.I | re.S)[:max_comments]
    comments = tuple(cleaned for fragment in fragments if (cleaned := _clean_comment(fragment)))
    if not count and not comments:
        return ReputationResult(PhoneSpamFilterClient.name, LookupStatus.NOT_FOUND, e164, url)
    return ReputationResult(
        source=PhoneSpamFilterClient.name,
        status=LookupStatus.FOUND,
        number=e164,
        url=url,
        security_level="Reported",
        report_count=int(count.group(1).replace(",", "")) if count else len(comments),
        comments=comments or None,
    )


def _clean_comment(fragment: str) -> str:
    fragment = re.sub(r"<em[^>]*>.*?</em>", "", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())
