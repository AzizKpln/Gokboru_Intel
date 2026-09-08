from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping


Loader = Callable[[urllib.request.Request, float], tuple[int, Any]]


class PublicUsernameProfilesClient:
    """Exact-match lookups against public, read-only profile endpoints."""

    def __init__(self, *, timeout_seconds: float = 20.0, loader: Loader | None = None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Username lookup timeout must be greater than zero.")
        self.timeout_seconds = timeout_seconds
        self.loader = loader or self._load

    def reddit(self, username: str) -> dict[str, Any]:
        url = f"https://www.reddit.com/user/{urllib.parse.quote(username, safe='')}/about.json"
        status, payload, error = self._request("reddit", url)
        if error:
            return error
        if status == 404:
            return self._missing("reddit")
        if status != 200 or not isinstance(payload, Mapping) or not isinstance(payload.get("data"), Mapping):
            return self._bad_status("reddit", status)
        data = payload["data"]
        if str(data.get("name", "")).casefold() != username.casefold():
            return self._missing("reddit")
        return self._found("reddit", {
            "username": data.get("name"), "name": data.get("subreddit", {}).get("title") if isinstance(data.get("subreddit"), Mapping) else None,
            "web_url": f"https://www.reddit.com/user/{urllib.parse.quote(str(data.get('name')), safe='')}/",
            "avatar_url": data.get("icon_img"), "created_utc": data.get("created_utc"),
            "comment_karma": data.get("comment_karma"), "link_karma": data.get("link_karma"),
            "is_gold": data.get("is_gold"), "verified": data.get("verified"),
        })

    def hackernews(self, username: str) -> dict[str, Any]:
        url = f"https://hacker-news.firebaseio.com/v0/user/{urllib.parse.quote(username, safe='')}.json"
        status, payload, error = self._request("hackernews", url)
        if error:
            return error
        if status == 404 or payload is None:
            return self._missing("hackernews")
        if status != 200 or not isinstance(payload, Mapping) or str(payload.get("id", "")).casefold() != username.casefold():
            return self._bad_status("hackernews", status) if status != 200 else self._missing("hackernews")
        return self._found("hackernews", {
            "username": payload.get("id"), "web_url": f"https://news.ycombinator.com/user?id={urllib.parse.quote(str(payload.get('id')))}",
            "created_utc": payload.get("created"), "karma": payload.get("karma"), "about": payload.get("about"),
        })

    def keybase(self, username: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"usernames": username})
        status, payload, error = self._request("keybase", f"https://keybase.io/_/api/1.0/user/lookup.json?{query}")
        if error:
            return error
        them = payload.get("them") if isinstance(payload, Mapping) else None
        item = them[0] if isinstance(them, list) and them else None
        basics = item.get("basics") if isinstance(item, Mapping) else None
        if status == 404 or not isinstance(basics, Mapping):
            return self._missing("keybase") if status in {200, 404} else self._bad_status("keybase", status)
        if str(basics.get("username", "")).casefold() != username.casefold():
            return self._missing("keybase")
        profile = item.get("profile") if isinstance(item.get("profile"), Mapping) else {}
        pictures = item.get("pictures") if isinstance(item.get("pictures"), Mapping) else {}
        return self._found("keybase", {
            "username": basics.get("username"), "name": profile.get("full_name"), "bio": profile.get("bio"),
            "location": profile.get("location"), "web_url": f"https://keybase.io/{urllib.parse.quote(str(basics.get('username')), safe='')}",
            "avatar_url": pictures.get("primary", {}).get("url") if isinstance(pictures.get("primary"), Mapping) else None,
            "created_at": basics.get("ctime"),
        })

    def dockerhub(self, username: str) -> dict[str, Any]:
        url = f"https://hub.docker.com/v2/users/{urllib.parse.quote(username, safe='')}/"
        status, payload, error = self._request("dockerhub", url)
        if error:
            return error
        if status == 404:
            return self._missing("dockerhub")
        if status != 200 or not isinstance(payload, Mapping) or str(payload.get("username", "")).casefold() != username.casefold():
            return self._bad_status("dockerhub", status) if status != 200 else self._missing("dockerhub")
        return self._found("dockerhub", {
            "username": payload.get("username"), "name": payload.get("full_name"), "bio": payload.get("bio"),
            "location": payload.get("location"), "company": payload.get("company"), "website_url": payload.get("profile_url"),
            "web_url": f"https://hub.docker.com/u/{urllib.parse.quote(str(payload.get('username')), safe='')}",
            "avatar_url": payload.get("gravatar_url"), "date_joined": payload.get("date_joined"),
        })

    def codeberg(self, username: str) -> dict[str, Any]:
        url = f"https://codeberg.org/api/v1/users/{urllib.parse.quote(username, safe='')}"
        status, payload, error = self._request("codeberg", url)
        if error:
            return error
        if status == 404:
            return self._missing("codeberg")
        if status != 200 or not isinstance(payload, Mapping) or str(payload.get("login", "")).casefold() != username.casefold():
            return self._bad_status("codeberg", status) if status != 200 else self._missing("codeberg")
        allowed = ("login", "full_name", "avatar_url", "language", "website", "location", "description", "created", "last_login", "followers_count", "following_count", "starred_repos_count")
        profile = {key: payload.get(key) for key in allowed if payload.get(key) not in (None, "")}
        profile["username"] = profile.pop("login")
        profile["name"] = profile.pop("full_name", None)
        profile["bio"] = profile.pop("description", None)
        profile["web_url"] = f"https://codeberg.org/{urllib.parse.quote(username, safe='')}"
        return self._found("codeberg", profile)

    def bitbucket(self, username: str) -> dict[str, Any]:
        url = f"https://api.bitbucket.org/2.0/users/{urllib.parse.quote(username, safe='')}"
        status, payload, error = self._request("bitbucket", url)
        if error:
            return error
        if status == 404:
            return self._missing("bitbucket")
        if status != 200 or not isinstance(payload, Mapping):
            return self._bad_status("bitbucket", status)
        nickname = str(payload.get("nickname") or payload.get("username") or "")
        if nickname.casefold() != username.casefold():
            return self._missing("bitbucket")
        links = payload.get("links") if isinstance(payload.get("links"), Mapping) else {}
        html = links.get("html") if isinstance(links.get("html"), Mapping) else {}
        avatar = links.get("avatar") if isinstance(links.get("avatar"), Mapping) else {}
        return self._found("bitbucket", {
            "username": nickname, "name": payload.get("display_name"), "web_url": html.get("href"),
            "avatar_url": avatar.get("href"), "created_at": payload.get("created_on"), "account_status": payload.get("account_status"),
        })

    def npm(self, username: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(f"org.couchdb.user:{username}", safe="")
        status, payload, error = self._request("npm", f"https://registry.npmjs.org/-/user/{encoded}")
        if error:
            return error
        if status == 404:
            return self._missing("npm")
        if status != 200 or not isinstance(payload, Mapping):
            return self._bad_status("npm", status)
        observed = str(payload.get("name") or "").removeprefix("org.couchdb.user:")
        if observed.casefold() != username.casefold():
            return self._missing("npm")
        return self._found("npm", {
            "username": observed, "web_url": f"https://www.npmjs.com/~{urllib.parse.quote(observed, safe='')}",
            "created_at": payload.get("date"),
        })

    def devto(self, username: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"url": username})
        status, payload, error = self._request("devto", f"https://dev.to/api/users/by_username?{query}")
        if error:
            return error
        if status == 404:
            return self._missing("devto")
        if status != 200 or not isinstance(payload, Mapping) or str(payload.get("username", "")).casefold() != username.casefold():
            return self._bad_status("devto", status) if status != 200 else self._missing("devto")
        fields = ("username", "name", "summary", "location", "website_url", "twitter_username", "github_username", "profile_image", "joined_at")
        profile = {key: payload.get(key) for key in fields if payload.get(key) not in (None, "")}
        profile["bio"] = profile.pop("summary", None)
        profile["avatar_url"] = profile.pop("profile_image", None)
        profile["web_url"] = f"https://dev.to/{urllib.parse.quote(username, safe='')}"
        return self._found("devto", profile)

    def lichess(self, username: str) -> dict[str, Any]:
        status, payload, error = self._request("lichess", f"https://lichess.org/api/user/{urllib.parse.quote(username, safe='')}")
        if error:
            return error
        if status == 404:
            return self._missing("lichess")
        if status != 200 or not isinstance(payload, Mapping) or str(payload.get("username", "")).casefold() != username.casefold():
            return self._bad_status("lichess", status) if status != 200 else self._missing("lichess")
        profile_data = payload.get("profile") if isinstance(payload.get("profile"), Mapping) else {}
        return self._found("lichess", {
            "username": payload.get("username"), "name": " ".join(str(profile_data.get(k, "")).strip() for k in ("firstName", "lastName")).strip(),
            "bio": profile_data.get("bio"), "location": profile_data.get("location"), "website_url": profile_data.get("links"),
            "web_url": f"https://lichess.org/@/{urllib.parse.quote(str(payload.get('username')), safe='')}",
            "created_at": payload.get("createdAt"), "last_seen_at": payload.get("seenAt"), "play_time": payload.get("playTime"),
            "count": payload.get("count"), "disabled": payload.get("disabled"), "online": payload.get("online"),
        })

    def chesscom(self, username: str) -> dict[str, Any]:
        status, payload, error = self._request("chesscom", f"https://api.chess.com/pub/player/{urllib.parse.quote(username, safe='')}")
        if error:
            return error
        if status == 404:
            return self._missing("chesscom")
        if status != 200 or not isinstance(payload, Mapping) or str(payload.get("username", "")).casefold() != username.casefold():
            return self._bad_status("chesscom", status) if status != 200 else self._missing("chesscom")
        fields = ("username", "name", "avatar", "location", "country", "followers", "joined", "last_online", "status", "is_streamer", "verified")
        profile = {key: payload.get(key) for key in fields if payload.get(key) not in (None, "")}
        profile["avatar_url"] = profile.pop("avatar", None)
        profile["web_url"] = str(payload.get("url") or f"https://www.chess.com/member/{urllib.parse.quote(username, safe='')}")
        return self._found("chesscom", profile)

    def _request(self, source: str, url: str) -> tuple[int, Any, dict[str, Any] | None]:
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Moriarty-V5 username-audit/1.0"})
        try:
            status, payload = self.loader(request, self.timeout_seconds)
            return status, payload, None
        except urllib.error.HTTPError as exc:
            if exc.code in {403, 429}:
                return exc.code, None, {"source": source, "status": "rate_limited", "profile": None}
            return exc.code, None, None
        except (OSError, urllib.error.URLError) as exc:
            return 0, None, {"source": source, "status": "provider_error", "profile": None, "note": str(exc)}

    @staticmethod
    def _found(source: str, profile: Mapping[str, Any]) -> dict[str, Any]:
        return {"source": source, "status": "found", "profile": {key: value for key, value in profile.items() if value not in (None, "")}}

    @staticmethod
    def _missing(source: str) -> dict[str, Any]:
        return {"source": source, "status": "not_found", "profile": None}

    @staticmethod
    def _bad_status(source: str, status: int) -> dict[str, Any]:
        return {"source": source, "status": "provider_error", "profile": None, "http_status": status}

    @staticmethod
    def _load(request: urllib.request.Request, timeout: float) -> tuple[int, Any]:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, json.loads(body) if body else None
