from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class HudsonRockSelfCheckError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HudsonRockSelfCheckResult:
    source: str
    number: str
    status: str
    exposed: bool | None
    infection_count: int | None
    stealer_families: tuple[str, ...]
    compromise_dates: tuple[str, ...]
    corporate_service_count: int | None
    personal_service_count: int | None
    api_version: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HudsonRockSelfCheckClient:
    LEGACY_URL = "https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-username"
    V3_URL = "https://api.hudsonrock.com/json/v3/search-by-login/usernames"

    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Hudson Rock timeout must be greater than zero.")
        self.analyzer = analyzer
        self.api_key = (api_key or os.getenv("HUDSONROCK_API_KEY", "")).strip()
        self.timeout_seconds = timeout_seconds

    def check_own_number(
        self, raw_number: str, region: str | None = None
    ) -> HudsonRockSelfCheckResult:
        phone = self.analyzer.analyze(raw_number, region)
        if not phone.is_valid:
            raise HudsonRockSelfCheckError("A valid phone number is required.")

        if self.api_key:
            request = urllib.request.Request(
                self.V3_URL,
                data=json.dumps({
                    "logins": [phone.e164],
                    "filter_credentials": True,
                    "sort_by": "date_compromised",
                    "sort_direction": "desc",
                }).encode("utf-8"),
                headers={
                    "api-key": self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "Moriarty-V5/1.0 defensive-self-check",
                },
                method="POST",
            )
            version = "v3"
        else:
            query = urllib.parse.urlencode({"username": phone.e164})
            request = urllib.request.Request(
                f"{self.LEGACY_URL}?{query}",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Moriarty-V5/1.0 defensive-self-check",
                },
            )
            version = "legacy_v2"

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            return self._http_error(phone.e164, exc.code, version)
        except urllib.error.URLError as exc:
            raise HudsonRockSelfCheckError(f"Hudson Rock request failed: {exc.reason}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HudsonRockSelfCheckError("Hudson Rock returned an unreadable response.") from exc

        return self._parse_payload(phone.e164, payload, version)

    @staticmethod
    def _parse_payload(number: str, payload: Any, version: str) -> HudsonRockSelfCheckResult:
        if not isinstance(payload, dict):
            raise HudsonRockSelfCheckError("Hudson Rock returned an unexpected response shape.")
        raw_records = payload.get("data") if version == "v3" else payload.get("stealers")
        records = raw_records if isinstance(raw_records, list) else []
        families: list[str] = []
        dates: list[str] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            family = str(record.get("stealer_family") or record.get("malware_family") or "").strip()
            date = str(record.get("date_compromised") or record.get("compromised_at") or "").strip()
            if family and family not in families:
                families.append(family)
            if date:
                short_date = date[:10]
                if short_date not in dates:
                    dates.append(short_date)
        found = bool(records)
        return HudsonRockSelfCheckResult(
            "hudsonrock_infostealer_self_check",
            number,
            "exposed" if found else "not_found",
            found,
            len(records),
            tuple(families),
            tuple(dates),
            HudsonRockSelfCheckClient._optional_int(payload.get("total_corporate_services")),
            HudsonRockSelfCheckClient._optional_int(payload.get("total_user_services")),
            version,
            (
                "Hudson Rock reported infostealer exposure. Moriarty retained only counts, dates, and malware-family labels; credentials, cookies, IP addresses, device names, and login URLs were discarded."
                if found
                else "Hudson Rock did not report an infostealer exposure for the supplied number."
            ),
        )

    @staticmethod
    def _http_error(number: str, code: int, version: str) -> HudsonRockSelfCheckResult:
        statuses = {
            401: ("api_key_required", "Hudson Rock requires a valid API key."),
            403: ("permission_denied", "The API key does not have permission for login search."),
            404: ("not_found", "Hudson Rock did not report a matching exposure."),
            408: ("timeout", "Hudson Rock timed out while processing the request."),
            429: ("rate_limited", "Hudson Rock rate-limited the request; retry later."),
        }
        status, note = statuses.get(code, ("provider_error", f"Hudson Rock returned HTTP {code}."))
        return HudsonRockSelfCheckResult(
            "hudsonrock_infostealer_self_check", number, status,
            False if status == "not_found" else None,
            0 if status == "not_found" else None,
            (), (), None, None, version, note,
        )

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
