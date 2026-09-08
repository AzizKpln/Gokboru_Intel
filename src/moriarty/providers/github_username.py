from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable


Loader = Callable[[urllib.request.Request, float], tuple[int, Any]]


class GitHubUsernameClient:
    URL = "https://api.github.com/users/{}"

    def __init__(self, *, token: str | None = None, timeout_seconds: float = 20.0, loader: Loader | None = None) -> None:
        self.token = (token or os.getenv("GITHUB_TOKEN", "")).strip()
        self.timeout_seconds = timeout_seconds
        self.loader = loader or self._load

    def lookup(self, username: str) -> dict[str, Any]:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "Moriarty-V5 username-audit"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.URL.format(urllib.parse.quote(username, safe="")), headers=headers)
        try:
            status, payload = self.loader(request, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            status, payload = exc.code, {}
        except (OSError, urllib.error.URLError) as exc:
            return {"source": "github", "status": "provider_error", "profile": None, "note": str(exc)}
        if status == 404:
            return {"source": "github", "status": "not_found", "profile": None}
        if status in {403, 429}:
            return {"source": "github", "status": "rate_limited", "profile": None}
        if status != 200 or not isinstance(payload, dict):
            return {"source": "github", "status": "provider_error", "profile": None, "http_status": status}
        fields = ("login", "html_url", "avatar_url", "name", "bio", "company", "location", "blog", "public_repos", "created_at", "updated_at")
        profile = {key: payload.get(key) for key in fields if payload.get(key) not in (None, "")}
        return {"source": "github", "status": "found", "profile": profile}

    @staticmethod
    def _load(request: urllib.request.Request, timeout: float) -> tuple[int, Any]:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace"))
