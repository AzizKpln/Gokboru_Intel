from __future__ import annotations
import html, json, re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from moriarty.domain.models import LookupStatus, ReputationResult
from moriarty.providers.whocalled_uk import PageResponse, ReputationSourceError
from moriarty.services.phone_analyzer import PhoneAnalyzer

class PhoneyaClient:
    name = "phoneya"
    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 8.0, loader=None) -> None:
        if timeout_seconds <= 0: raise ValueError("Source timeout must be greater than zero.")
        self._analyzer, self._timeout_seconds = analyzer, timeout_seconds
        self._loader = loader or _load_page
    def lookup(self, raw_number: str, default_region: str | None = None) -> ReputationResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        url = f"https://www.phoneya.com/{phone.e164.removeprefix('+')}"
        response = self._loader(url, self._timeout_seconds)
        if response.status == 404: return ReputationResult(self.name, LookupStatus.NOT_FOUND, phone.e164, url)
        if response.status != 200: raise ReputationSourceError(f"Phoneya returned HTTP {response.status}.")
        return _parse_page(response.body, phone.e164, url)

def _load_page(url: str, timeout: float) -> PageResponse:
    request = Request(url, headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8","Accept-Language":"en-US,en;q=0.9"})
    try:
        with urlopen(request, timeout=timeout) as response: return PageResponse(response.status, response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
    except HTTPError as exc:
        if exc.code == 404: return PageResponse(404, "")
        raise ReputationSourceError(f"Phoneya returned HTTP {exc.code}.") from exc
    except URLError as exc: raise ReputationSourceError(f"Phoneya network error: {exc.reason}") from exc

def _parse_page(body: str, e164: str, url: str) -> ReputationResult:
    description = ""
    for raw in re.findall(r'<script\s+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', body, re.I | re.S):
        try:
            value = json.loads(html.unescape(raw))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict) and value.get("@type") == "WebPage":
            description = str(value.get("description") or "")
            break
    match = re.search(r"has\s+([\d,]+)\s+(.+?)\s+complaints?\s+on file", description, re.I)
    if not match: return ReputationResult(PhoneyaClient.name, LookupStatus.NOT_FOUND, e164, url)
    count = int(match.group(1).replace(",", ""))
    label = " ".join(match.group(2).split()).upper()
    return ReputationResult(source=PhoneyaClient.name, status=LookupStatus.FOUND, number=e164, url=url, security_level="Reported", report_count=count, categories={f"{label} complaints": count})
