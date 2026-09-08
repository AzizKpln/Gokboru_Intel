from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class OpenSanctionsPhoneSearchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OpenSanctionsPhoneMatch:
    entity_id: str
    caption: str
    schema: str | None
    topics: tuple[str, ...]
    datasets: tuple[str, ...]
    countries: tuple[str, ...]
    matched_phone: str
    entity_url: str


@dataclass(frozen=True, slots=True)
class OpenSanctionsPhoneSearchResult:
    source: str
    number: str
    status: str
    dataset: str
    total_matches: int
    matches: tuple[OpenSanctionsPhoneMatch, ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OpenSanctionsPhoneSearchClient:
    URL = "https://api.opensanctions.org/search"

    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        *,
        api_key: str | None = None,
        dataset: str = "default",
        max_results: int = 20,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not re.fullmatch(r"[a-z0-9_-]+", dataset):
            raise ValueError("Invalid OpenSanctions dataset name.")
        if not 1 <= max_results <= 50:
            raise ValueError("OpenSanctions result limit must be between 1 and 50.")
        self.analyzer = analyzer
        self.api_key = (api_key or os.getenv("OPENSANCTIONS_API_KEY", "")).strip()
        self.dataset = dataset
        self.max_results = max_results
        self.timeout_seconds = timeout_seconds

    def search(self, raw_number: str, region: str | None = None) -> OpenSanctionsPhoneSearchResult:
        phone = self.analyzer.analyze(raw_number, region)
        if not phone.is_valid:
            raise OpenSanctionsPhoneSearchError("A valid phone number is required.")
        if not self.api_key:
            return self._result(phone.e164, "configuration_required", (), "Set OPENSANCTIONS_API_KEY or use --api-key.")
        
        
        
        
        query = urllib.parse.urlencode({"q": f'"{phone.e164}"', "limit": self.max_results})
        request = urllib.request.Request(
            f"{self.URL}/{self.dataset}?{query}",
            headers={"Accept": "application/json", "Authorization": f"ApiKey {self.api_key}", "User-Agent": "Moriarty-V5/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            status = "authentication_failed" if exc.code in {401, 403} else "rate_limited" if exc.code == 429 else "provider_error"
            try:
                error_body = exc.read().decode("utf-8", "replace").strip()
            except Exception:
                error_body = ""
            detail = self._error_detail(error_body)
            note = f"OpenSanctions returned HTTP {exc.code}."
            if detail:
                note = f"{note} {detail}"
            return self._result(phone.e164, status, (), note)
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise OpenSanctionsPhoneSearchError(f"OpenSanctions request failed: {exc}") from exc
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        matches: list[OpenSanctionsPhoneMatch] = []
        target_digits = re.sub(r"\D", "", phone.e164)
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            properties = row.get("properties") if isinstance(row.get("properties"), dict) else {}
            phones = self._strings(properties.get("phone") or properties.get("phones"))
            matched = next((item for item in phones if re.sub(r"\D", "", item) == target_digits), None)
            if not matched:
                continue
            entity_id = str(row.get("id") or "").strip()
            if not entity_id:
                continue
            matches.append(OpenSanctionsPhoneMatch(
                entity_id,
                str(row.get("caption") or row.get("name") or "Unnamed entity").strip(),
                str(row.get("schema")).strip() if row.get("schema") else None,
                self._strings(properties.get("topics") or row.get("topics")),
                self._strings(row.get("datasets")),
                self._strings(properties.get("country") or properties.get("countries")),
                matched,
                f"https://www.opensanctions.org/entities/{urllib.parse.quote(entity_id, safe='')}/",
            ))
        return self._result(
            phone.e164, "found" if matches else "not_found", tuple(matches),
            "Only exact phone-field matches were retained. Search queries are sent to OpenSanctions and may appear in provider access logs.",
        )

    @staticmethod
    def _strings(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,) if value.strip() else ()
        if isinstance(value, list):
            return tuple(str(item).strip() for item in value if str(item).strip())
        return ()

    @staticmethod
    def _error_detail(body: str) -> str:
        if not body:
            return ""
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return re.sub(r"\s+", " ", body)[:300]
        if not isinstance(payload, dict):
            return ""
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, str):
            return re.sub(r"\s+", " ", detail).strip()[:300]
        return ""

    def _result(self, number: str, status: str, matches: tuple[OpenSanctionsPhoneMatch, ...], note: str) -> OpenSanctionsPhoneSearchResult:
        return OpenSanctionsPhoneSearchResult("opensanctions_phone_search", number, status, self.dataset, len(matches), matches, note)
