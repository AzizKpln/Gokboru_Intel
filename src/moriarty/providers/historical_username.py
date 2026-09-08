from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class HistoricalUsernameClient:
    TEMPLATES = (
        "https://github.com/{username}", "https://www.reddit.com/user/{username}",
        "https://x.com/{username}", "https://twitter.com/{username}",
        "https://www.instagram.com/{username}/", "https://www.tiktok.com/@{username}",
        "https://www.twitch.tv/{username}", "https://{username}.tumblr.com/",
    )

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = min(float(timeout_seconds), 10.0)

    def wayback(self, username: str) -> dict[str, Any]:
        mentions, checks = [], []
        for template in self.TEMPLATES:
            target = template.format(username=urllib.parse.quote(username, safe=""))
            query = urllib.parse.urlencode({"url": target, "output": "json", "filter": "statuscode:200", "fl": "timestamp,original,statuscode,digest", "collapse": "digest", "limit": "2"})
            endpoint = "https://web.archive.org/cdx/search/cdx?" + query
            try:
                payload = self._json(endpoint)
            except urllib.error.HTTPError as exc:
                checks.append({"url": target, "status": "unverified", "http_status": exc.code}); continue
            except (OSError, ValueError) as exc:
                checks.append({"url": target, "status": "unverified", "note": str(exc)}); continue
            rows = payload[1:] if isinstance(payload, list) and payload and isinstance(payload[0], list) else []
            for row in rows:
                if not isinstance(row, list) or len(row) < 2: continue
                timestamp, original = str(row[0]), str(row[1])
                mentions.append({"entity_type": "historical_mention", "username": username, "name": "Wayback capture", "web_url": f"https://web.archive.org/web/{timestamp}/{original}", "original_url": original, "captured_at": timestamp, "archive": "wayback"})
            checks.append({"url": target, "status": "found" if rows else "not_found", "capture_count": len(rows)})
        return {"source": "wayback", "status": "found" if mentions else "not_found" if all(c["status"] == "not_found" for c in checks) else "partial", "profile": None, "profiles": mentions, "checks": checks}

    def commoncrawl(self, username: str) -> dict[str, Any]:
        try:
            collections = self._json("https://index.commoncrawl.org/collinfo.json")
            index = str(collections[0]["id"])
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            return {"source": "commoncrawl", "status": "provider_error", "profile": None, "profiles": [], "note": str(exc)}
        mentions, checks = [], []
        for template in self.TEMPLATES:
            target = template.format(username=urllib.parse.quote(username, safe=""))
            endpoint = f"https://index.commoncrawl.org/{index}-index?" + urllib.parse.urlencode({"url": target, "output": "json", "filter": "status:200", "collapse": "digest"})
            try:
                text = self._text(endpoint)
                rows = [json.loads(line) for line in text.splitlines() if line.strip()][:2]
            except urllib.error.HTTPError as exc:
                rows = []
                if exc.code != 404: checks.append({"url": target, "status": "unverified", "http_status": exc.code}); continue
            except (OSError, ValueError) as exc:
                checks.append({"url": target, "status": "unverified", "note": str(exc)}); continue
            for row in rows:
                mentions.append({"entity_type": "historical_mention", "username": username, "name": "Common Crawl capture", "web_url": str(row.get("url") or target), "original_url": str(row.get("url") or target), "captured_at": row.get("timestamp"), "archive": "commoncrawl", "crawl": index})
            checks.append({"url": target, "status": "found" if rows else "not_found", "capture_count": len(rows)})
        return {"source": "commoncrawl", "status": "found" if mentions else "not_found" if all(c["status"] == "not_found" for c in checks) else "partial", "profile": None, "profiles": mentions, "checks": checks}

    def _json(self, url: str) -> Any:
        return json.loads(self._text(url))

    def _text(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Gokboru-Intelligence/1.0 (public archive lookup)"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read().decode("utf-8", "replace")
