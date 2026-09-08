from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class FediverseUsernameClient:
    INSTANCES = ("mastodon.social", "mas.to", "fosstodon.org", "infosec.exchange", "hachyderm.io")

    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = min(float(timeout_seconds), 8.0)

    def search(self, username: str) -> dict[str, Any]:
        profiles, checks = [], []
        for instance in self.INSTANCES:
            url = f"https://{instance}/api/v1/accounts/lookup?" + urllib.parse.urlencode({"acct": username})
            request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Gokboru-Intelligence/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    data = json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                checks.append({"instance": instance, "status": "not_found" if exc.code == 404 else "unverified", "http_status": exc.code})
                continue
            except (OSError, ValueError) as exc:
                checks.append({"instance": instance, "status": "unverified", "note": str(exc)})
                continue
            acct = str(data.get("acct") or "")
            if str(data.get("username") or "").casefold() != username.casefold():
                checks.append({"instance": instance, "status": "not_found"})
                continue
            profile_url = str(data.get("url") or f"https://{instance}/@{username}")
            profiles.append({
                "username": username, "name": data.get("display_name") or acct or username,
                "web_url": profile_url, "avatar_url": data.get("avatar_static") or data.get("avatar"),
                "bio": data.get("note"), "category": "federated_social", "fediverse_address": acct or f"{username}@{instance}",
                "instance": instance, "discoverable": data.get("discoverable"),
            })
            checks.append({"instance": instance, "status": "found", "url": profile_url})
        conclusive = sum(item["status"] in {"found", "not_found"} for item in checks)
        return {
            "source": "fediverse", "status": "found" if profiles else "not_found" if conclusive == len(checks) else "partial",
            "profile": None, "profiles": profiles, "checks": checks, "found_count": len(profiles),
        }
