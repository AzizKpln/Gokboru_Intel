from __future__ import annotations

import csv
import io
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class FTCDNCError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FTCDNCResult:
    source: str
    number: str
    status: str
    complaint_count: int
    robocall_count: int
    first_reported: str | None
    last_reported: str | None
    subjects: tuple[dict[str, Any], ...]
    states: tuple[dict[str, Any], ...]
    coverage_days: int
    files_checked: int
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FTCDNCClient:
    CSV_URL = "https://www.ftc.gov/sites/default/files/DNC_Complaint_Numbers_{day}.csv"

    def __init__(self, analyzer: PhoneAnalyzer, *, coverage_days: int = 7, timeout_seconds: float = 30.0, **_: Any) -> None:
        if not 1 <= coverage_days <= 31:
            raise ValueError("FTC coverage must be between 1 and 31 days.")
        self.analyzer = analyzer
        self.coverage_days = coverage_days
        self.timeout_seconds = timeout_seconds

    def search(self, raw_number: str, region: str | None = None) -> FTCDNCResult:
        phone = self.analyzer.analyze(raw_number, region)
        if not phone.is_valid:
            raise FTCDNCError("A valid phone number is required.")
        if phone.region_code != "US":
            return self._result(phone.e164, "unsupported_country", [], 0, "FTC complaint files cover United States calls only.")
        target = re.sub(r"\D", "", phone.e164)[1:]
        records: list[dict[str, str]] = []
        files_checked = 0
        for offset in range(self.coverage_days):
            day = date.today() - timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            request = urllib.request.Request(self.CSV_URL.format(day=day.isoformat()), headers={"User-Agent": "Moriarty-V5/1.0", "Accept": "text/csv"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    content = response.read().decode("utf-8-sig", "replace")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                raise FTCDNCError(f"FTC CSV returned HTTP {exc.code}.") from exc
            except urllib.error.URLError as exc:
                raise FTCDNCError(f"FTC CSV request failed: {exc.reason}") from exc
            files_checked += 1
            for row in csv.DictReader(io.StringIO(content)):
                normalized = {re.sub(r"[^a-z0-9]", "", str(k).casefold()): str(v or "") for k, v in row.items()}
                if re.sub(r"\D", "", normalized.get("companyphonenumber", "")) == target:
                    records.append(normalized)
        return self._result(phone.e164, "complaints_found" if records else "not_found", records, files_checked, "FTC complaints are unverified consumer reports; results cover only available daily files in the recent window.")

    def _result(self, number: str, status: str, records: list[dict[str, str]], files_checked: int, note: str) -> FTCDNCResult:
        subjects = Counter(r.get("subject") or "Unknown" for r in records)
        states = Counter(r.get("consumerstate") or "Unknown" for r in records)
        dates = sorted((r.get("createddate") or "")[:10] for r in records if r.get("createddate"))
        robocalls = sum((r.get("recordedmessageorrobocall") or "").upper() in {"Y", "YES", "TRUE"} for r in records)
        return FTCDNCResult("ftc_dnc_reported_calls", number, status, len(records), robocalls, dates[0] if dates else None, dates[-1] if dates else None, tuple({"category": k, "count": v} for k, v in subjects.most_common()), tuple({"state": k, "count": v} for k, v in states.most_common()), self.coverage_days, files_checked, note)
