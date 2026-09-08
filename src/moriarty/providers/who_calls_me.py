from __future__ import annotations
import html, re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from moriarty.domain.models import LookupStatus, ReputationResult
from moriarty.providers.whocalled_uk import PageResponse, ReputationSourceError
from moriarty.services.phone_analyzer import PhoneAnalyzer

class WhoCallsMeClient:
    name = "who_calls_me"
    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 8.0, loader=None, max_comments: int = 10) -> None:
        if timeout_seconds <= 0: raise ValueError("Source timeout must be greater than zero.")
        if max_comments < 0: raise ValueError("Maximum comments cannot be negative.")
        self._analyzer, self._timeout_seconds = analyzer, timeout_seconds
        self._loader, self._max_comments = loader or _load_page, max_comments
    def lookup(self, raw_number: str, default_region: str | None = None) -> ReputationResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        digits = phone.e164.removeprefix("+")
        if phone.country_code != 1 or len(digits) != 11:
            return ReputationResult(self.name, LookupStatus.NOT_APPLICABLE, phone.e164, None)
        url = f"https://whocallsme.com/Phone-Number.aspx/{digits[1:]}"
        response = self._loader(url, self._timeout_seconds)
        if response.status == 404: return ReputationResult(self.name, LookupStatus.NOT_FOUND, phone.e164, url)
        if response.status != 200: raise ReputationSourceError(f"WhoCallsMe returned HTTP {response.status}.")
        return _parse_page(response.body, phone.e164, url, self._max_comments)

def _load_page(url: str, timeout: float) -> PageResponse:
    request = Request(url, headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8","Accept-Language":"en-US,en;q=0.9"})
    try:
        with urlopen(request, timeout=timeout) as response: return PageResponse(response.status, response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
    except HTTPError as exc:
        if exc.code == 404: return PageResponse(404, "")
        raise ReputationSourceError(f"WhoCallsMe returned HTTP {exc.code}.") from exc
    except URLError as exc: raise ReputationSourceError(f"WhoCallsMe network error: {exc.reason}") from exc

def _parse_page(body: str, e164: str, url: str, max_comments: int) -> ReputationResult:
    fragments = re.findall(r'<div\s+class=["\']oos_contletBody["\'][^>]*>(.*?)</div>', body, re.I | re.S)[:max_comments]
    comments = tuple(cleaned for fragment in fragments if (cleaned := _clean(fragment)))
    callers: dict[str, int] = {}
    for value in re.findall(r"Caller:\s*([^<]+)</li>", body, re.I):
        name = html.unescape(value).strip()
        callers[name] = callers.get(name, 0) + 1
    if not comments: return ReputationResult(WhoCallsMeClient.name, LookupStatus.NOT_FOUND, e164, url)
    return ReputationResult(source=WhoCallsMeClient.name, status=LookupStatus.FOUND, number=e164, url=url, security_level="Reported", categories=callers or None, comments=comments)

def _clean(fragment: str) -> str: return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())
