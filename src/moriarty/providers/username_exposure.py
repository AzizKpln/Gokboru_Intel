from __future__ import annotations

import hashlib
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


JsonLoader = Callable[[urllib.request.Request, float], tuple[int, Any]]
TextLoader = Callable[[urllib.request.Request, float], tuple[int, str, str]]


class UsernameExposureClient:
    BREACH_DIRECTORY_URL = "https://breachdirectory.p.rapidapi.com/"

    def __init__(self, *, timeout_seconds: float = 30.0, breachdirectory_key: str | None = None, json_loader: JsonLoader | None = None, text_loader: TextLoader | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.breachdirectory_key = (breachdirectory_key or os.getenv("BREACHDIRECTORY_API_KEY", "") or os.getenv("RAPIDAPI_KEY", "")).strip()
        self.json_loader = json_loader or self._load_json
        self.text_loader = text_loader or self._load_text

    def breachdirectory(self, username: str) -> dict[str, Any]:
        if not self.breachdirectory_key:
            return self._configuration("breachdirectory", "Set BREACHDIRECTORY_API_KEY or --breachdirectory-key. The source remains optional.")
        query = urllib.parse.urlencode({"func": "auto", "term": username})
        request = urllib.request.Request(f"{self.BREACH_DIRECTORY_URL}?{query}", headers={
            "Accept": "application/json", "X-RapidAPI-Key": self.breachdirectory_key,
            "X-RapidAPI-Host": "breachdirectory.p.rapidapi.com", "User-Agent": "Gokboru-Intelligence/1.0",
        })
        try:
            status, payload = self.json_loader(request, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                return {"source": "breachdirectory", "status": "authentication_failed", "profile": None, "matches": [], "http_status": exc.code}
            if exc.code == 429:
                return {"source": "breachdirectory", "status": "rate_limited", "profile": None, "matches": [], "http_status": exc.code}
            return self._error("breachdirectory", f"HTTP {exc.code}")
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return self._error("breachdirectory", str(exc))
        if status != 200 or not isinstance(payload, Mapping):
            return self._error("breachdirectory", f"HTTP {status}")
        raw_records = payload.get("result") or payload.get("results") or payload.get("data") or []
        if isinstance(raw_records, Mapping):
            raw_records = [raw_records]
        matches: list[dict[str, Any]] = []
        if isinstance(raw_records, list):
            for record_index, record in enumerate(raw_records, 1):
                if not isinstance(record, Mapping):
                    continue
                raw_sources = record.get("sources") or record.get("source") or []
                sources = [str(value) for value in raw_sources] if isinstance(raw_sources, list) else [str(raw_sources)] if raw_sources else []
                exposed_fields = []
                for key, label in (("username", "username"), ("email", "email"), ("has_password", "password"), ("phone", "phone"), ("name", "name")):
                    value = record.get(key)
                    if value not in (None, "", False, [], {}):
                        exposed_fields.append(label)
                password_exposed = bool(record.get("has_password") or record.get("password") or record.get("hash") or record.get("sha1"))
                hash_types = []
                if record.get("sha1"):
                    hash_types.append("sha1")
                if record.get("hash"):
                    hash_types.append("provider_hash")
                risk = "high" if password_exposed else "medium" if any(field in exposed_fields for field in ("email", "phone", "name")) else "low"
                matches.append({
                    "record": record_index, "sources": sources, "source_count": len(sources),
                    "exposed_fields": exposed_fields, "password_exposed": password_exposed,
                    "provider_returned_password_mask": bool(record.get("password")), "hash_types_observed": hash_types,
                    "risk": risk, "credential_material_returned": False,
                })
        found_count = payload.get("found")
        found = bool(matches) or (isinstance(found_count, int) and found_count > 0)
        if not found:
            return self._clear("breachdirectory")
        result = self._found("breachdirectory", matches, "BreachDirectory metadata only; credential values and personal identifiers were deliberately suppressed.")
        result["risk"] = "high" if any(match["risk"] == "high" for match in matches) else "medium" if matches else "low"
        result["data_handling"] = {
            "password_fragments_returned": False, "hash_values_returned": False,
            "email_values_returned": False, "username_values_returned": False,
        }
        return result

    def ahmia(self, username: str, limit: int = 20) -> dict[str, Any]:
        query = urllib.parse.urlencode({"q": f'"{username}"'})
        url = f"https://ahmia.fi/search/?{query}"
        request = urllib.request.Request(url, headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0 Gokboru-Intelligence/1.0"})
        try:
            status, body, final_url = self.text_loader(request, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            if exc.code in {403, 429}:
                return {"source": "ahmia", "status": "access_blocked", "profile": None, "matches": [], "http_status": exc.code}
            return self._error("ahmia", f"HTTP {exc.code}")
        except (OSError, urllib.error.URLError) as exc:
            return self._error("ahmia", str(exc))
        if status != 200:
            return self._error("ahmia", f"HTTP {status}")
        matches: list[dict[str, Any]] = []
        
        blocks = re.findall(r"<li[^>]*class=[\"'][^\"']*result[^\"']*[\"'][^>]*>(.*?)</li>", body, re.I | re.S)
        for block in blocks[: max(1, min(limit, 100))]:
            plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(block))).strip()
            if username.casefold() not in plain.casefold():
                continue
            title_match = re.search(r"<h\d[^>]*>(.*?)</h\d>", block, re.I | re.S)
            title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(title_match.group(1)))).strip() if title_match else "Indexed mention"
            matches.append({"title": title[:300], "snippet": plain[:500], "evidence_url": final_url})
        return self._found("ahmia", matches, "Matches came from Ahmia's clearnet index; onion destinations were not opened.") if matches else self._clear("ahmia")

    def local_files(self, username: str, paths: Sequence[str], limit: int = 100) -> dict[str, Any]:
        if not paths:
            return self._configuration("localbreach", "Pass one or more --breach-path values.")
        matches: list[dict[str, Any]] = []
        checked = 0
        allowed = {".txt", ".csv", ".tsv", ".json", ".jsonl", ".log"}
        needle = username.casefold()
        for raw_path in paths:
            root = Path(raw_path).expanduser()
            candidates = (root.rglob("*") if root.is_dir() else (root,))
            for path in candidates:
                if len(matches) >= limit or not path.is_file() or path.suffix.casefold() not in allowed:
                    continue
                checked += 1
                try:
                    with path.open("r", encoding="utf-8", errors="replace") as stream:
                        for line_number, line in enumerate(stream, 1):
                            if needle in line.casefold():
                                digest = hashlib.sha256(line.encode("utf-8", "replace")).hexdigest()
                                matches.append({"file": str(path.resolve()), "line_number": line_number, "line_sha256": digest, "content_returned": False})
                                if len(matches) >= limit:
                                    break
                except OSError:
                    continue
        payload = self._found("localbreach", matches, "Matched line contents were not returned; only file, line number and SHA-256 evidence were stored.") if matches else self._clear("localbreach")
        payload["checked_files"] = checked
        return payload

    @staticmethod
    def _found(source: str, matches: list[dict[str, Any]], note: str) -> dict[str, Any]:
        return {"source": source, "status": "found", "profile": None, "matches": matches, "match_count": len(matches), "note": note}

    @staticmethod
    def _clear(source: str) -> dict[str, Any]:
        return {"source": source, "status": "not_found", "profile": None, "matches": [], "match_count": 0}

    @staticmethod
    def _configuration(source: str, note: str) -> dict[str, Any]:
        return {"source": source, "status": "configuration_required", "profile": None, "matches": [], "note": note}

    @staticmethod
    def _error(source: str, note: str) -> dict[str, Any]:
        return {"source": source, "status": "provider_error", "profile": None, "matches": [], "note": note}

    @staticmethod
    def _load_json(request: urllib.request.Request, timeout: float) -> tuple[int, Any]:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", "replace"))

    @staticmethod
    def _load_text(request: urllib.request.Request, timeout: float) -> tuple[int, str, str]:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(2_000_000).decode("utf-8", "replace"), response.geturl()
