from __future__ import annotations
import html, re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from moriarty.domain.models import LookupStatus, ReputationResult
from moriarty.providers.whocalled_uk import PageResponse, ReputationSourceError
from moriarty.services.phone_analyzer import PhoneAnalyzer

class UnknownPhoneClient:
    name = "unknownphone"
    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 8.0, loader=None, max_comments: int = 10) -> None:
        if timeout_seconds <= 0: raise ValueError("Source timeout must be greater than zero.")
        if max_comments < 0: raise ValueError("Maximum comments cannot be negative.")
        self._analyzer, self._timeout_seconds = analyzer, timeout_seconds
        self._loader, self._max_comments = loader or _load_page, max_comments
    def lookup(self, raw_number: str, default_region: str | None = None) -> ReputationResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        url = f"https://www.unknownphone.com/phone/{phone.e164.removeprefix('+')}"
        response = self._loader(url, self._timeout_seconds)
        if response.status == 404: return ReputationResult(self.name, LookupStatus.NOT_FOUND, phone.e164, url)
        if response.status != 200: raise ReputationSourceError(f"UnknownPhone returned HTTP {response.status}.")
        return _parse_page(response.body, phone.e164, url, self._max_comments)

def _load_page(url: str, timeout: float) -> PageResponse:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-GB,en;q=0.9"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return PageResponse(response.status, response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
    except HTTPError as exc:
        if exc.code == 404: return PageResponse(404, "")
        raise ReputationSourceError(f"UnknownPhone returned HTTP {exc.code}.") from exc
    except URLError as exc: raise ReputationSourceError(f"UnknownPhone network error: {exc.reason}") from exc

def _parse_page(body: str, e164: str, url: str, max_comments: int) -> ReputationResult:
    match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']\s*/?>', body, re.I | re.S)
    description = html.unescape(match.group(1)) if match else ""
    rating = re.search(r"rated as\s+([A-Za-z ]+?)(?:\.|,)", description, re.I) or re.search(r"marked as a potential\s+([A-Za-z ]+?)\s+number", description, re.I)
    reports = re.search(r"reported\s+([\d,]+)\s+times", description, re.I)
    calls = re.search(r"detected(?:\s+more than)?\s+([\d,]+)\s+calls", description, re.I)
    count = re.search(r'itemprop=["\']commentCount["\']\s+content=["\'](\d+)["\']', body, re.I)
    comments = tuple(cleaned for fragment in re.findall(r'<p\s+itemprop=["\']text["\'][^>]*>(.*?)</p>', body, re.I | re.S)[:max_comments] if (cleaned := _clean(fragment)))
    level = rating.group(1).strip().title() if rating else None
    report_count = _number(reports.group(1)) if reports else (int(count.group(1)) if count else None)
    if not level and report_count is None and not comments: return ReputationResult(UnknownPhoneClient.name, LookupStatus.NOT_FOUND, e164, url)
    return ReputationResult(UnknownPhoneClient.name, LookupStatus.FOUND, e164, url, security_level=level, report_count=report_count, detected_call_count=_number(calls.group(1)) if calls else None, comments=comments or None)

def _number(value: str) -> int: return int(value.replace(",", ""))
def _clean(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I))).split())
