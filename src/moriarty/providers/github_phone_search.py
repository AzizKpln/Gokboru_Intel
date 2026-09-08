from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class GitHubPhoneSearchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GitHubPhoneMatch:
    repository: str
    path: str
    url: str
    matched_variant: str


@dataclass(frozen=True, slots=True)
class GitHubPhoneSearchResult:
    source: str
    number: str
    status: str
    total_matches: int
    matches: tuple[GitHubPhoneMatch, ...]
    variants_searched: tuple[str, ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubPhoneSearchClient:
    URL = "https://api.github.com/search/code"

    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        *,
        token: str | None = None,
        max_results: int = 20,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not 1 <= max_results <= 100:
            raise ValueError("GitHub result limit must be between 1 and 100.")
        if timeout_seconds <= 0:
            raise ValueError("GitHub timeout must be greater than zero.")
        self.analyzer = analyzer
        self.token = (token or os.getenv("GITHUB_TOKEN", "")).strip()
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds

    def search_own_number(
        self, raw_number: str, region: str | None = None
    ) -> GitHubPhoneSearchResult:
        phone = self.analyzer.analyze(raw_number, region)
        if not phone.is_valid:
            raise GitHubPhoneSearchError("A valid phone number is required.")
        if not self.token:
            return GitHubPhoneSearchResult(
                "github_public_code_phone_search", phone.e164,
                "api_key_required", 0, (), self._variants(phone),
                "GitHub code search requires GITHUB_TOKEN or --github-token.",
            )

        variants = self._variants(phone)
        matches: list[GitHubPhoneMatch] = []
        seen: set[tuple[str, str]] = set()
        for variant in variants:
            remaining = self.max_results - len(matches)
            if remaining <= 0:
                break
            query = urllib.parse.urlencode({
                "q": f'"{variant}"',
                "per_page": min(remaining, 100),
                "page": 1,
            })
            request = urllib.request.Request(
                f"{self.URL}?{query}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "Moriarty-V5/1.0 defensive-self-check",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                return self._http_error(phone.e164, variants, exc.code)
            except urllib.error.URLError as exc:
                raise GitHubPhoneSearchError(f"GitHub request failed: {exc.reason}") from exc
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise GitHubPhoneSearchError("GitHub returned an unreadable response.") from exc

            for item in payload.get("items", []) if isinstance(payload, dict) else []:
                if not isinstance(item, dict):
                    continue
                repository = item.get("repository")
                if not isinstance(repository, dict) or repository.get("private") is True:
                    continue
                repo_name = str(repository.get("full_name") or "").strip()
                path = str(item.get("path") or "").strip()
                url = str(item.get("html_url") or "").strip()
                key = (repo_name.casefold(), path)
                if repo_name and path and url and key not in seen:
                    seen.add(key)
                    matches.append(GitHubPhoneMatch(repo_name, path, url, variant))
                    if len(matches) >= self.max_results:
                        break

        return GitHubPhoneSearchResult(
            "github_public_code_phone_search", phone.e164,
            "found" if matches else "not_found", len(matches), tuple(matches), variants,
            (
                "The number was found in public GitHub code-search metadata. Moriarty did not download file contents or include private repositories."
                if matches
                else "GitHub code search did not report the supplied number in public repository files."
            ),
        )

    @staticmethod
    def _variants(phone: Any) -> tuple[str, ...]:
        values = (
            phone.e164,
            phone.e164.lstrip("+"),
            phone.international_format,
            phone.national_format,
        )
        return tuple(dict.fromkeys(value.strip() for value in values if value and value.strip()))

    @staticmethod
    def _http_error(number: str, variants: tuple[str, ...], code: int) -> GitHubPhoneSearchResult:
        statuses = {
            401: ("api_key_required", "The GitHub token is missing, expired, or invalid."),
            403: ("rate_limited", "GitHub denied or rate-limited code search; check token permissions and retry later."),
            422: ("query_rejected", "GitHub rejected the code-search query."),
            429: ("rate_limited", "GitHub rate-limited code search; retry later."),
        }
        status, note = statuses.get(code, ("provider_error", f"GitHub returned HTTP {code}."))
        return GitHubPhoneSearchResult(
            "github_public_code_phone_search", number, status, 0, (), variants, note
        )
