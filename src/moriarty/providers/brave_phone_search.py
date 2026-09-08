from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class BravePhoneSearchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BravePhoneMatch:
    title: str
    url: str
    domain: str
    snippet: str
    matched_variant: str


@dataclass(frozen=True, slots=True)
class BravePhoneSearchResult:
    source: str
    number: str
    status: str
    total_matches: int
    variants_searched: tuple[str, ...]
    matches: tuple[BravePhoneMatch, ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BravePhoneSearchClient:
    URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, analyzer: PhoneAnalyzer, *, api_key: str | None = None, max_results: int = 20, timeout_seconds: float = 30.0) -> None:
        self.analyzer = analyzer
        self.api_key = (api_key or os.getenv("BRAVE_SEARCH_API_KEY", "")).strip()
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds

    def search(self, raw_number: str, region: str | None = None) -> BravePhoneSearchResult:
        phone = self.analyzer.analyze(raw_number, region)
        if not phone.is_valid:
            raise BravePhoneSearchError("A valid phone number is required.")
        variants = tuple(dict.fromkeys(v for v in (phone.e164, phone.e164.lstrip("+"), phone.international_format, phone.national_format) if v))
        if not self.api_key:
            return BravePhoneSearchResult("brave_public_phone_search", phone.e164, "configuration_required", 0, variants, (), "Set BRAVE_SEARCH_API_KEY or use --api-key.")
        matches: list[BravePhoneMatch] = []
        seen: set[str] = set()
        for variant in variants:
            if len(matches) >= self.max_results:
                break
            query = urllib.parse.urlencode({"q": f'"{variant}"', "count": min(20, self.max_results - len(matches)), "safesearch": "strict"})
            request = urllib.request.Request(f"{self.URL}?{query}", headers={"Accept": "application/json", "X-Subscription-Token": self.api_key})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                return BravePhoneSearchResult("brave_public_phone_search", phone.e164, "authentication_failed" if exc.code in {401, 403} else "rate_limited" if exc.code == 429 else "provider_error", 0, variants, (), f"Brave Search returned HTTP {exc.code}.")
            except (urllib.error.URLError, json.JSONDecodeError) as exc:
                raise BravePhoneSearchError(f"Brave Search request failed: {exc}") from exc
            results = payload.get("web", {}).get("results", []) if isinstance(payload, dict) else []
            for item in results:
                url = str(item.get("url") or "").strip() if isinstance(item, dict) else ""
                if not url or url in seen:
                    continue
                seen.add(url)
                matches.append(BravePhoneMatch(
                    " ".join(str(item.get("title") or "Untitled").split())[:300], url,
                    urllib.parse.urlparse(url).netloc, " ".join(str(item.get("description") or "").split())[:500], variant,
                ))
                if len(matches) >= self.max_results:
                    break
        return BravePhoneSearchResult("brave_public_phone_search", phone.e164, "found" if matches else "not_found", len(matches), variants, tuple(matches), "Only indexed public-web result metadata was retained; matches do not establish ownership.")
