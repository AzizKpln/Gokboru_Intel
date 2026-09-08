from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse

import phonenumbers

from moriarty.providers.search_backend import SearchBackend
from moriarty.services.phone_analyzer import PhoneAnalyzer


@dataclass(frozen=True, slots=True)
class PastebinLeakFinding:
    title: str
    url: str
    matched_query: str


@dataclass(frozen=True, slots=True)
class PastebinLeakAuditResult:
    source: str
    number: str
    status: str
    findings: tuple[PastebinLeakFinding, ...]
    searched_queries: tuple[str, ...]
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


class PastebinLeakAuditService:
    """Find public search-index references to an owned phone number on Pastebin.

    The service deliberately does not download paste bodies or return adjacent
    leaked fields.  A hit means only that a public search index linked a
    Pastebin URL to an exact phone-number representation.
    """

    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        backend: SearchBackend,
        max_results: int = 10,
    ) -> None:
        if max_results <= 0:
            raise ValueError("Pastebin result limit must be greater than zero.")
        self._analyzer = analyzer
        self._backend = backend
        self._max_results = max_results

    def audit(self, raw_number: str, region: str | None = None) -> PastebinLeakAuditResult:
        phone = self._analyzer.analyze(raw_number, region)
        queries = _pastebin_queries(phone.e164)
        findings: list[PastebinLeakFinding] = []
        seen: set[str] = set()

        for query in queries:
            remaining = self._max_results - len(findings)
            if remaining <= 0:
                break
            for result in self._backend.search(query, remaining):
                url = _pastebin_url(result.url)
                if not url or url in seen:
                    continue
                seen.add(url)
                findings.append(PastebinLeakFinding(result.title, url, query))
                if len(findings) >= self._max_results:
                    break

        status = "exposed" if findings else "not_found"
        note = (
            "Public search results linked the exact phone number to Pastebin. "
            "Paste contents and adjacent leaked data were not downloaded."
            if findings
            else
            "No indexed Pastebin result was found. This does not prove the number has never appeared in a paste."
        )
        return PastebinLeakAuditResult(
            "pastebin_public_index", phone.e164, status, tuple(findings), queries, note
        )


def _pastebin_queries(e164: str) -> tuple[str, ...]:
    parsed = phonenumbers.parse(e164, None)
    variants = (
        e164,
        e164.removeprefix("+"),
        phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
        phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL),
    )
    return tuple(dict.fromkeys(f'site:pastebin.com "{value}"' for value in variants))


def _pastebin_url(raw_url: str) -> str | None:
    parsed = urlparse(raw_url)
    host = parsed.netloc.lower().split(":", 1)[0].removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or host != "pastebin.com":
        return None
    path = parsed.path.rstrip("/")
    if not path or path in {"/login", "/signup", "/archive"}:
        return None
    return f"https://pastebin.com{path}"
