from __future__ import annotations

import json
import base64
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class RedditPhoneSearchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RedditPhoneMatch:
    subreddit: str
    title: str
    url: str
    created: str | None
    score: int
    matched_variant: str


@dataclass(frozen=True, slots=True)
class RedditPhoneSearchResult:
    source: str
    number: str
    status: str
    total_matches: int
    matches: tuple[RedditPhoneMatch, ...]
    variants_searched: tuple[str, ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RedditPhoneSearchClient:
    URL = "https://www.reddit.com/r/all/search.json"
    OAUTH_URL = "https://oauth.reddit.com/r/all/search"
    TOKEN_URL = "https://www.reddit.com/api/v1/access_token"

    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        user_agent: str | None = None,
        max_results: int = 20,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not 1 <= max_results <= 100:
            raise ValueError("Reddit result limit must be between 1 and 100.")
        if timeout_seconds <= 0:
            raise ValueError("Reddit timeout must be greater than zero.")
        self.analyzer = analyzer
        self.client_id = (client_id or os.getenv("REDDIT_CLIENT_ID", "")).strip()
        self.client_secret = (client_secret or os.getenv("REDDIT_CLIENT_SECRET", "")).strip()
        self.user_agent = (
            user_agent or os.getenv("REDDIT_USER_AGENT", "")
            or "linux:Moriarty-V5:1.0 (by /u/your_reddit_username)"
        ).strip()
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds

    def search_own_number(
        self, raw_number: str, region: str | None = None
    ) -> RedditPhoneSearchResult:
        phone = self.analyzer.analyze(raw_number, region)
        if not phone.is_valid:
            raise RedditPhoneSearchError("A valid phone number is required.")
        variants = self._variants(phone)
        oauth_token = self._application_token() if self.client_id and self.client_secret else None
        matches: list[RedditPhoneMatch] = []
        seen: set[str] = set()

        for variant in variants:
            remaining = self.max_results - len(matches)
            if remaining <= 0:
                break
            query = urllib.parse.urlencode({
                "q": f'"{variant}"',
                "restrict_sr": "false",
                "sort": "relevance",
                "t": "all",
                "limit": min(remaining, 100),
                "raw_json": 1,
            })
            headers = {"Accept": "application/json", "User-Agent": self.user_agent}
            endpoint = self.URL
            if oauth_token:
                endpoint = self.OAUTH_URL
                headers["Authorization"] = f"bearer {oauth_token}"
            request = urllib.request.Request(f"{endpoint}?{query}", headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                return self._http_error(phone.e164, variants, exc.code, bool(oauth_token))
            except urllib.error.URLError as exc:
                raise RedditPhoneSearchError(f"Reddit request failed: {exc.reason}") from exc
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RedditPhoneSearchError("Reddit returned an unreadable response.") from exc

            children = (
                payload.get("data", {}).get("children", [])
                if isinstance(payload, dict) else []
            )
            for child in children:
                post = child.get("data", {}) if isinstance(child, dict) else {}
                if not isinstance(post, dict):
                    continue
                permalink = str(post.get("permalink") or "").strip()
                if not permalink:
                    continue
                url = urllib.parse.urljoin("https://www.reddit.com", permalink)
                if url in seen:
                    continue
                seen.add(url)
                matches.append(RedditPhoneMatch(
                    subreddit=str(post.get("subreddit") or "").strip(),
                    title=" ".join(str(post.get("title") or "Untitled").split())[:300],
                    url=url,
                    created=self._date(post.get("created_utc")),
                    score=self._score(post.get("score")),
                    matched_variant=variant,
                ))
                if len(matches) >= self.max_results:
                    break

        return RedditPhoneSearchResult(
            "reddit_public_phone_search", phone.e164,
            "found" if matches else "not_found", len(matches), tuple(matches), variants,
            (
                "The number appeared in public Reddit search metadata. Moriarty retained only post titles, subreddit names, dates, scores, and links."
                if matches
                else "Reddit public search did not report a matching post for the supplied number."
            ),
        )

    def _application_token(self) -> str:
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode("utf-8")
        ).decode("ascii")
        request = urllib.request.Request(
            self.TOKEN_URL,
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("ascii"),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise RedditPhoneSearchError("Reddit client ID or client secret is invalid.") from exc
            raise RedditPhoneSearchError(f"Reddit OAuth returned HTTP {exc.code}.") from exc
        except urllib.error.URLError as exc:
            raise RedditPhoneSearchError(f"Reddit OAuth failed: {exc.reason}") from exc
        token = str(payload.get("access_token") or "") if isinstance(payload, dict) else ""
        if not token:
            raise RedditPhoneSearchError("Reddit OAuth did not return an access token.")
        return token

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
    def _date(value: Any) -> str | None:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    @staticmethod
    def _score(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _http_error(
        number: str, variants: tuple[str, ...], code: int, authenticated: bool = False
    ) -> RedditPhoneSearchResult:
        statuses = {
            401: ("authentication_required", "Reddit requires authentication for this request."),
            403: (
                "permission_denied" if authenticated else "access_blocked",
                "Reddit denied the OAuth search request; verify API access and app permissions."
                if authenticated else
                "Reddit blocked anonymous search. Configure REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET for OAuth.",
            ),
            429: ("rate_limited", "Reddit rate-limited the request; retry later."),
        }
        status, note = statuses.get(code, ("provider_error", f"Reddit returned HTTP {code}."))
        return RedditPhoneSearchResult(
            "reddit_public_phone_search", number, status, 0, (), variants, note
        )
