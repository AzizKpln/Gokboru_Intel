from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping


JsonLoader = Callable[[urllib.request.Request, float], tuple[int, Any]]
TextLoader = Callable[[urllib.request.Request, float], tuple[int, str, str]]


class SocialUsernameProfilesClient:
    """Read-only exact profile checks for public social and identity services."""

    def __init__(self, *, timeout_seconds: float = 20.0, json_loader: JsonLoader | None = None, text_loader: TextLoader | None = None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Username lookup timeout must be greater than zero.")
        self.timeout_seconds = timeout_seconds
        self.json_loader = json_loader or self._load_json
        self.text_loader = text_loader or self._load_text

    def bluesky(self, username: str) -> dict[str, Any]:
        actor = username if "." in username else f"{username}.bsky.social"
        query = urllib.parse.urlencode({"actor": actor})
        request = self._request(f"https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?{query}")
        try:
            status, payload = self.json_loader(request, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            return self._http_error("bluesky", exc.code)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return self._provider_error("bluesky", exc)
        if status != 200 or not isinstance(payload, Mapping):
            return self._status_error("bluesky", status)
        handle = str(payload.get("handle") or "")
        if handle.casefold() != actor.casefold():
            return self._not_found("bluesky")
        profile = self._clean({
            "username": handle, "did": payload.get("did"), "name": payload.get("displayName"),
            "bio": payload.get("description"), "avatar_url": payload.get("avatar"), "banner_url": payload.get("banner"),
            "web_url": f"https://bsky.app/profile/{urllib.parse.quote(handle, safe='.')}",
            "followers_count": payload.get("followersCount"), "follows_count": payload.get("followsCount"),
            "posts_count": payload.get("postsCount"), "created_at": payload.get("createdAt"),
        })
        return {"source": "bluesky", "status": "found", "profile": profile}

    def telegram(self, username: str) -> dict[str, Any]:
        url = f"https://t.me/{urllib.parse.quote(username, safe='')}"
        try:
            status, body, final_url = self.text_loader(self._request(url, accept="text/html"), self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            return self._http_error("telegram", exc.code)
        except (OSError, urllib.error.URLError) as exc:
            return self._provider_error("telegram", exc)
        if status != 200:
            return self._status_error("telegram", status)
        
        title = self._meta(body, "og:title")
        description = self._meta(body, "og:description")
        image = self._meta(body, "og:image")
        canonical = self._canonical(body) or final_url
        if not title or "tgme_page" not in body or f"t.me/{username}".casefold() not in canonical.casefold():
            return self._not_found("telegram")
        profile = self._clean({"username": username, "name": title, "bio": description, "avatar_url": image, "web_url": canonical})
        return {"source": "telegram", "status": "found", "profile": profile}

    def gravatar(self, username: str) -> dict[str, Any]:
        url = f"https://en.gravatar.com/{urllib.parse.quote(username, safe='')}.json"
        try:
            status, payload = self.json_loader(self._request(url), self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            return self._http_error("gravatar", exc.code)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return self._provider_error("gravatar", exc)
        entries = payload.get("entry") if isinstance(payload, Mapping) else None
        entry = entries[0] if isinstance(entries, list) and entries else None
        if status != 200 or not isinstance(entry, Mapping):
            return self._status_error("gravatar", status) if status != 200 else self._not_found("gravatar")
        preferred = str(entry.get("preferredUsername") or username)
        if preferred.casefold() != username.casefold():
            return self._not_found("gravatar")
        photos = entry.get("photos") if isinstance(entry.get("photos"), list) else []
        profile = self._clean({
            "username": preferred, "name": entry.get("displayName"), "bio": entry.get("aboutMe"),
            "location": entry.get("currentLocation"), "avatar_url": photos[0].get("value") if photos and isinstance(photos[0], Mapping) else None,
            "web_url": entry.get("profileUrl") or f"https://gravatar.com/{urllib.parse.quote(preferred, safe='')}",
        })
        return {"source": "gravatar", "status": "found", "profile": profile}

    def roblox(self, username: str) -> dict[str, Any]:
        body = json.dumps({"usernames": [username], "excludeBannedUsers": False}).encode("utf-8")
        request = urllib.request.Request("https://users.roblox.com/v1/usernames/users", data=body, method="POST", headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Moriarty-V5 username-audit/1.0"})
        try:
            status, payload = self.json_loader(request, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            return self._http_error("roblox", exc.code)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return self._provider_error("roblox", exc)
        items = payload.get("data") if isinstance(payload, Mapping) else None
        item = next((value for value in items if isinstance(value, Mapping) and str(value.get("requestedUsername") or value.get("name") or "").casefold() == username.casefold()), None) if isinstance(items, list) else None
        if status != 200:
            return self._status_error("roblox", status)
        if not isinstance(item, Mapping):
            return self._not_found("roblox")
        user_id = item.get("id")
        return {"source": "roblox", "status": "found", "profile": self._clean({
            "username": item.get("name"), "name": item.get("displayName"), "user_id": user_id,
            "web_url": f"https://www.roblox.com/users/{user_id}/profile" if user_id is not None else None,
            "has_verified_badge": item.get("hasVerifiedBadge"),
        })}

    @staticmethod
    def _request(url: str, accept: str = "application/json") -> urllib.request.Request:
        return urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "Moriarty-V5 username-audit/1.0"})

    @staticmethod
    def _meta(body: str, property_name: str) -> str | None:
        pattern = rf'<meta[^>]+property=["\']{re.escape(property_name)}["\'][^>]+content=["\']([^"\']*)'
        match = re.search(pattern, body, re.IGNORECASE)
        return html.unescape(match.group(1)).strip() if match else None

    @staticmethod
    def _canonical(body: str) -> str | None:
        match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', body, re.IGNORECASE)
        return html.unescape(match.group(1)).strip() if match else None

    @staticmethod
    def _clean(profile: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in profile.items() if value not in (None, "")}

    @staticmethod
    def _not_found(source: str) -> dict[str, Any]:
        return {"source": source, "status": "not_found", "profile": None}

    @staticmethod
    def _provider_error(source: str, exc: Exception) -> dict[str, Any]:
        return {"source": source, "status": "provider_error", "profile": None, "note": str(exc)}

    @classmethod
    def _http_error(cls, source: str, status: int) -> dict[str, Any]:
        if status == 404:
            return cls._not_found(source)
        if status in {401, 403, 429}:
            return {"source": source, "status": "access_blocked", "profile": None, "http_status": status}
        return cls._status_error(source, status)

    @staticmethod
    def _status_error(source: str, status: int) -> dict[str, Any]:
        return {"source": source, "status": "provider_error", "profile": None, "http_status": status}

    @staticmethod
    def _load_json(request: urllib.request.Request, timeout: float) -> tuple[int, Any]:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace"))

    @staticmethod
    def _load_text(request: urllib.request.Request, timeout: float) -> tuple[int, str, str]:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace"), response.geturl()
