from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from time import monotonic
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4


class AuditSourceState(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    FAILED = "failed"


class AuditFindingState(StrEnum):
    FINDING = "finding"
    CLEAR = "clear"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class PhoneAuditSource:
    name: str
    category: str
    description: str
    requires_configuration: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PhoneAuditSourceResult:
    source: str
    category: str
    state: AuditSourceState
    finding: AuditFindingState
    provider_status: str
    duration_ms: int
    data: Mapping[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PhoneAuditSummary:
    requested: int
    completed: int
    findings: int
    clear: int
    indeterminate: int
    skipped: int
    blocked: int
    failed: int


@dataclass(frozen=True, slots=True)
class PhoneAuditResult:
    schema_version: str
    audit_id: str
    started_at: str
    completed_at: str
    duration_ms: int
    number: str
    region: str | None
    status: str
    summary: PhoneAuditSummary
    sources: tuple[PhoneAuditSourceResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


AuditRunner = Callable[[], Any]


class PhoneAuditCore:
    """Provider-neutral phone audit orchestration and result normalization."""

    def __init__(self, catalog: Sequence[PhoneAuditSource]) -> None:
        self._catalog = {source.name: source for source in catalog}

    @property
    def catalog(self) -> tuple[PhoneAuditSource, ...]:
        return tuple(self._catalog.values())

    def run(self, *, number: str, region: str | None, selected_sources: Sequence[str], runners: Mapping[str, AuditRunner]) -> PhoneAuditResult:
        unknown = tuple(name for name in selected_sources if name not in self._catalog)
        if unknown:
            raise ValueError(f"Unknown phone-audit source(s): {', '.join(unknown)}")
        if not selected_sources:
            raise ValueError("Select at least one phone-audit source.")
        started_wall = datetime.now(timezone.utc)
        started = monotonic()
        results: list[PhoneAuditSourceResult] = []
        for name in dict.fromkeys(selected_sources):
            source = self._catalog[name]
            runner = runners.get(name)
            if runner is None:
                results.append(PhoneAuditSourceResult(name, source.category, AuditSourceState.SKIPPED, AuditFindingState.INDETERMINATE, "not_configured", 0, error="No runner was configured for this source."))
                continue
            source_started = monotonic()
            try:
                data = self._mapping(runner())
                provider_status = str(data.get("status", "completed")).lower()
                state, finding, provider_status = self._normalize_source(name, provider_status, data)
                results.append(PhoneAuditSourceResult(name, source.category, state, finding, provider_status, max(0, round((monotonic() - source_started) * 1000)), data=data))
            except Exception as exc:
                results.append(PhoneAuditSourceResult(name, source.category, AuditSourceState.FAILED, AuditFindingState.INDETERMINATE, "error", max(0, round((monotonic() - source_started) * 1000)), error=str(exc) or type(exc).__name__))
        summary = self._summary(results)
        status = "completed" if summary.completed == summary.requested else "partial" if summary.completed else "failed"
        completed_wall = datetime.now(timezone.utc)
        return PhoneAuditResult("1.0", str(uuid4()), started_wall.isoformat(), completed_wall.isoformat(), max(0, round((monotonic() - started) * 1000)), number, region, status, summary, tuple(results))

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        if hasattr(value, "to_dict"):
            value = value.to_dict()
        elif hasattr(value, "__dataclass_fields__"):
            value = asdict(value)
        if not isinstance(value, Mapping):
            raise TypeError("Audit source must return a mapping or a serializable result object.")
        return value

    @staticmethod
    def _normalize(status: str) -> tuple[AuditSourceState, AuditFindingState]:
        if status in {"found", "exposed", "registered", "match", "matches", "risky", "complaints_found"}:
            return AuditSourceState.COMPLETED, AuditFindingState.FINDING
        if status in {"not_found", "not_exposed", "not_registered", "clear", "safe", "no_results"}:
            return AuditSourceState.COMPLETED, AuditFindingState.CLEAR
        if status in {"configuration_required", "not_configured", "not_applicable", "unsupported"}:
            return AuditSourceState.SKIPPED, AuditFindingState.INDETERMINATE
        if status in {"access_blocked", "captcha", "rate_limited", "authentication_failed", "permission_denied", "login_required", "manual_action_required", "search_limit_exceeded", "subscription_required", "account_restricted"}:
            return AuditSourceState.BLOCKED, AuditFindingState.INDETERMINATE
        if status == "consent_declined":
            return AuditSourceState.SKIPPED, AuditFindingState.INDETERMINATE
        if status in {"provider_error", "error", "timeout", "page_changed"}:
            return AuditSourceState.FAILED, AuditFindingState.INDETERMINATE
        return AuditSourceState.COMPLETED, AuditFindingState.INDETERMINATE

    @classmethod
    def _normalize_source(
        cls, source: str, status: str, data: Mapping[str, Any]
    ) -> tuple[AuditSourceState, AuditFindingState, str]:
        """Translate provider-specific payload shapes without altering raw data."""
        if source == "documents" and status in {"success", "partial"}:
            count = cls._nested_count(data, ("count", "documents", "findings"))
            normalized = "found" if count > 0 else "not_found" if status == "success" else "inconclusive"
            state, finding = cls._normalize(normalized)
            return state, finding, normalized
        if source == "web-mentions" and status in {"completed", "success", "partial"}:
            count = cls._direct_count(data, ("count", "mentions"))
            normalized = "found" if count > 0 else "not_found"
            state, finding = cls._normalize(normalized)
            return state, finding, normalized
        if source == "reputation" and status in {"success", "partial"}:
            summary = data.get("reputation_summary")
            found = summary.get("found_sources", 0) if isinstance(summary, Mapping) else 0
            normalized = "found" if cls._integer(found) > 0 else "not_found" if status == "success" else "inconclusive"
            state, finding = cls._normalize(normalized)
            return state, finding, normalized
        if source == "business" and status in {"success", "partial"}:
            count = cls._nested_count(data, ("listings",))
            normalized = "found" if count > 0 else "not_found" if status == "success" else "inconclusive"
            state, finding = cls._normalize(normalized)
            return state, finding, normalized
        if source == "disposable" and "classification" in data:
            classification = str(data.get("classification") or "")
            if classification == "possible_public_sms_number":
                normalized = "found"
            elif classification == "not_observed_on_checked_directory_pages":
                normalized = "not_found"
            else:
                normalized = "inconclusive"
            state, finding = cls._normalize(normalized)
            return state, finding, normalized
        state, finding = cls._normalize(status)
        return state, finding, status

    @classmethod
    def _nested_count(cls, data: Mapping[str, Any], keys: tuple[str, ...]) -> int:
        total = 0
        providers = data.get("providers")
        if not isinstance(providers, (list, tuple)):
            return cls._direct_count(data, keys)
        for provider in providers:
            if not isinstance(provider, Mapping):
                continue
            nested = provider.get("data")
            if isinstance(nested, Mapping):
                total += cls._direct_count(nested, keys)
        return total

    @classmethod
    def _direct_count(cls, data: Mapping[str, Any], keys: tuple[str, ...]) -> int:
        counts: list[int] = []
        for key in keys:
            value = data.get(key)
            if isinstance(value, (list, tuple, set)):
                counts.append(len(value))
            if value is not None and not isinstance(value, (Mapping, str)):
                counts.append(cls._integer(value))
        return max(counts, default=0)

    @staticmethod
    def _integer(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _summary(results: Sequence[PhoneAuditSourceResult]) -> PhoneAuditSummary:
        return PhoneAuditSummary(len(results), sum(item.state is AuditSourceState.COMPLETED for item in results), sum(item.finding is AuditFindingState.FINDING for item in results), sum(item.finding is AuditFindingState.CLEAR for item in results), sum(item.finding is AuditFindingState.INDETERMINATE for item in results), sum(item.state is AuditSourceState.SKIPPED for item in results), sum(item.state is AuditSourceState.BLOCKED for item in results), sum(item.state is AuditSourceState.FAILED for item in results))


DEFAULT_PHONE_AUDIT_SOURCES = (
    PhoneAuditSource("local", "identity", "Local normalization, validity, region, carrier and line type."),
    PhoneAuditSource("truecaller", "caller_identity", "Own-number lookup through Microsoft-authenticated Truecaller.", ("MICROSOFT_EMAIL", "MICROSOFT_PASSWORD")),
    PhoneAuditSource("syncme", "caller_identity", "Own-number lookup through Microsoft-authenticated Sync.me.", ("MICROSOFT_EMAIL", "MICROSOFT_PASSWORD")),
    PhoneAuditSource("telegram", "social_presence", "Own Telegram account lookup using the official client API.", ("TELEGRAM_API_ID", "TELEGRAM_API_HASH")),
    PhoneAuditSource("facebook", "social_presence", "Manual own-number Facebook recovery observation without selecting a recovery method."),
    PhoneAuditSource("whatsapp", "social_presence", "Own-number WhatsApp click-to-chat observation without sending a message."),
    PhoneAuditSource("cybernews", "breach_exposure", "Own-number Cybernews leak-check result."),
    PhoneAuditSource("databreach", "breach_exposure", "Own-number DataBreach.com exposure categories."),
    PhoneAuditSource("hudsonrock", "breach_exposure", "Own-number summarized infostealer exposure.", ("HUDSONROCK_API_KEY",)),
    PhoneAuditSource("github", "public_web", "Exact-number mentions in public GitHub repository metadata.", ("GITHUB_TOKEN (optional)",)),
    PhoneAuditSource("reddit", "public_web", "Exact-number mentions in public Reddit post metadata.", ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET")),
    PhoneAuditSource("brave", "public_web", "Exact-number mentions in Brave Search.", ("BRAVE_SEARCH_API_KEY",)),
    PhoneAuditSource("duckduckgo", "public_web", "Exact-number mentions in DuckDuckGo Search."),
    PhoneAuditSource("web-mentions", "public_web", "Gemini-grounded discovery and optional verification of public phone mentions.", ("GEMINI_API_KEY",)),
    PhoneAuditSource("pastebin", "breach_exposure", "Gemini-grounded discovery of indexed Pastebin mentions.", ("GEMINI_API_KEY",)),
    PhoneAuditSource("documents", "documents", "Gemini-grounded public PDF/DOCX/XLSX discovery with optional OCR and extraction.", ("GEMINI_API_KEY",)),
    PhoneAuditSource("reputation", "reputation", "Regional public phone reputation sources."),
    PhoneAuditSource("business", "business", "Public business listings and official-site verification."),
    PhoneAuditSource("disposable", "line_intelligence", "Public temporary-SMS directory signals."),
    PhoneAuditSource("opensanctions", "watchlists", "Exact structured phone matches in OpenSanctions.", ("OPENSANCTIONS_API_KEY",)),
    PhoneAuditSource("ftc", "complaints", "Official US FTC unwanted-call complaint files."),
    PhoneAuditSource("btk", "carrier", "Official BTK/e-Devlet number portability observation."),
)
