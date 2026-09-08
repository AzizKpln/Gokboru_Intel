from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence


class WhatsMyNameClient:
    CATALOG_URL = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"

    def __init__(self, *, timeout_seconds: float = 15.0, catalog_path: str | None = None, max_workers: int = 20) -> None:
        self.timeout_seconds = timeout_seconds
        self.catalog_path = Path(catalog_path).expanduser() if catalog_path else Path.home() / ".cache" / "moriarty" / "wmn-data.json"
        self.max_workers = max(1, min(max_workers, 32))

    def search(self, username: str, *, categories: Sequence[str] = (), limit: int = 500, include_nsfw: bool = False, refresh: bool = False) -> dict[str, Any]:
        try:
            catalog, origin = self._catalog(refresh)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"source": "whatsmyname", "status": "provider_error", "profile": None, "profiles": [], "note": str(exc)}
        requested_categories = {value.strip().casefold() for value in categories if value.strip()}
        sites = []
        for raw in catalog.get("sites", []) if isinstance(catalog, Mapping) else []:
            if not isinstance(raw, Mapping) or raw.get("valid") is False:
                continue
            category = str(raw.get("cat") or "misc")
            if category == "xx NSFW xx" and not include_nsfw:
                continue
            if requested_categories and category.casefold() not in requested_categories:
                continue
            if not raw.get("uri_check") or "{account}" not in str(raw.get("uri_check")) and not raw.get("post_body"):
                continue
            sites.append(raw)
            if len(sites) >= max(1, min(limit, 1000)):
                break

        def check(site: Mapping[str, Any]) -> dict[str, Any]:
            protections = {str(value).casefold() for value in site.get("protection", []) if value}
            if protections & {"captcha", "user-auth"}:
                return {"site": site.get("name"), "category": site.get("cat"), "status": "access_blocked", "reason": ",".join(sorted(protections))}
            account = username
            for character in str(site.get("strip_bad_char") or ""):
                account = account.replace(character, "")
            quoted = urllib.parse.quote(account, safe="")
            url = str(site.get("uri_check")).replace("{account}", quoted)
            pretty = str(site.get("uri_pretty") or site.get("uri_check")).replace("{account}", quoted)
            headers = {"User-Agent": "Mozilla/5.0 Gokboru-Intelligence/1.0", "Accept": "text/html,application/json"}
            headers.update({str(key): str(value) for key, value in site.get("headers", {}).items()} if isinstance(site.get("headers"), Mapping) else {})
            data = None
            method = "GET"
            if site.get("post_body"):
                data = str(site["post_body"]).replace("{account}", account).encode("utf-8")
                method = "POST"
            request = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    status = response.status
                    body = response.read(2_000_000).decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                status = exc.code
                try:
                    body = exc.read(2_000_000).decode("utf-8", "replace")
                except Exception:
                    body = ""
            except (OSError, urllib.error.URLError) as exc:
                return {"site": site.get("name"), "category": site.get("cat"), "status": "provider_error", "note": str(exc)}
            exists_code = int(site.get("e_code", 200))
            missing_code = int(site.get("m_code", 404))
            exists_text = str(site.get("e_string") or "")
            missing_text = str(site.get("m_string") or "")
            exists = status == exists_code and (not exists_text or exists_text in body)
            missing = status == missing_code and (not missing_text or missing_text in body)
            if exists and not missing:
                return {"site": site.get("name"), "category": site.get("cat"), "status": "found", "username": account, "web_url": pretty}
            if missing and not exists:
                return {"site": site.get("name"), "category": site.get("cat"), "status": "not_found"}
            return {"site": site.get("name"), "category": site.get("cat"), "status": "indeterminate", "http_status": status}

        with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(sites))), thread_name_prefix="wmn") as executor:
            checks = list(executor.map(check, sites))
        profiles = [{"username": item["username"], "name": item["site"], "web_url": item["web_url"], "category": item.get("category"), "catalog": "WhatsMyName"} for item in checks if item.get("status") == "found"]
        conclusive = sum(item.get("status") in {"found", "not_found"} for item in checks)
        return {
            "source": "whatsmyname", "status": "found" if profiles else "not_found" if conclusive == len(checks) else "partial",
            "profile": None, "profiles": profiles, "checks": checks,
            "checked_count": len(checks), "found_count": len(profiles), "catalog_origin": origin,
            "license": "CC BY-SA 4.0 — WebBreacher/WhatsMyName",
        }

    def _catalog(self, refresh: bool) -> tuple[Mapping[str, Any], str]:
        if self.catalog_path.is_file() and not refresh:
            return json.loads(self.catalog_path.read_text(encoding="utf-8")), str(self.catalog_path)
        request = urllib.request.Request(self.CATALOG_URL, headers={"Accept": "application/json", "User-Agent": "Gokboru-Intelligence/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=max(15.0, self.timeout_seconds)) as response:
                payload = response.read().decode("utf-8", "replace")
        except (OSError, urllib.error.URLError) as exc:
            if self.catalog_path.is_file():
                return json.loads(self.catalog_path.read_text(encoding="utf-8")), str(self.catalog_path)
            raise OSError(f"WhatsMyName catalog could not be loaded: {exc}") from exc
        parsed = json.loads(payload)
        if not isinstance(parsed, Mapping) or not isinstance(parsed.get("sites"), list):
            raise ValueError("WhatsMyName catalog has an invalid structure.")
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self.catalog_path.write_text(payload, encoding="utf-8")
        return parsed, self.CATALOG_URL
