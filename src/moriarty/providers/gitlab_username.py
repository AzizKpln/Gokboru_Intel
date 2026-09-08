from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable


Loader = Callable[[urllib.request.Request, float], tuple[int, Any]]


class GitLabUsernameClient:
    URL = "https://gitlab.com/api/v4/users"

    def __init__(self, *, timeout_seconds: float = 20.0, loader: Loader | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.loader = loader or self._load

    def lookup(self, username: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"username": username})
        request = urllib.request.Request(f"{self.URL}?{query}", headers={"User-Agent": "Moriarty-V5 username-audit"})
        try:
            status, payload = self.loader(request, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            status, payload = exc.code, []
        except (OSError, urllib.error.URLError) as exc:
            return {"source": "gitlab", "status": "provider_error", "profile": None, "note": str(exc)}
        if status in {403, 429}:
            return {"source": "gitlab", "status": "rate_limited", "profile": None}
        if status != 200 or not isinstance(payload, list):
            return {"source": "gitlab", "status": "provider_error", "profile": None, "http_status": status}
        match = next((item for item in payload if isinstance(item, dict) and str(item.get("username", "")).casefold() == username.casefold()), None)
        if match is None:
            return {"source": "gitlab", "status": "not_found", "profile": None}
        fields = ("username", "name", "web_url", "avatar_url", "state", "created_at", "bio", "location", "organization", "website_url")
        profile = {key: match.get(key) for key in fields if match.get(key) not in (None, "")}
        return {"source": "gitlab", "status": "found", "profile": profile}

    @staticmethod
    def _load(request: urllib.request.Request, timeout: float) -> tuple[int, Any]:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace"))
