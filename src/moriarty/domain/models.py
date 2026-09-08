from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Source:
    """Provenance attached to facts returned by future providers."""

    provider: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class Evidence:
    """A source-attributed observation usable by discovery modules."""

    kind: str
    value: str
    source: Source
    confidence: float | None = None
    attributes: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PhoneAnalysis:
    input_number: str
    e164: str
    is_possible: bool
    is_valid: bool
    region_code: str | None
    region_description: str
    country_code: int
    carrier: str
    timezones: tuple[str, ...]
    number_type: str = "unknown"
    national_format: str = ""
    international_format: str = ""
    rfc3966: str = ""
    national_destination_code: str = ""
    subscriber_number: str = ""
    is_mobile: bool = False
    is_fixed_line: bool = False
    is_voip: bool = False
    is_toll_free: bool = False
    is_premium_rate: bool = False
    is_shared_cost: bool = False
    is_personal_number: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProviderStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class InvestigationStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class MentionCategory(StrEnum):
    SOCIAL_PROFILE = "social_profile"
    BUSINESS_LISTING = "business_listing"
    FORUM = "forum"
    DOCUMENT = "document"
    PHONE_REPUTATION = "phone_reputation"
    OTHER = "other"


class LookupStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class InvestigationQuery:
    phone_number: str
    default_region: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderOutput:
    data: Mapping[str, Any]
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderResult:
    provider: str
    status: ProviderStatus
    duration_ms: int
    data: Mapping[str, Any] | None = None
    evidence: tuple[Evidence, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class InvestigationResult:
    query: InvestigationQuery
    status: InvestigationStatus
    providers: tuple[ProviderResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class WebMention:
    title: str
    url: str
    domain: str
    category: MentionCategory
    matched_query: str
    confidence: float
    verification: Mapping[str, Any] | None = None
    intelligence: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class WebMentionsResult:
    queries: tuple[str, ...]
    mentions: tuple[WebMention, ...]
    discovered_count: int = 0
    rejected: tuple[Mapping[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ReputationResult:
    source: str
    status: LookupStatus
    number: str
    url: str | None
    security_level: str | None = None
    report_count: int | None = None
    lookup_count: int | None = None
    categories: Mapping[str, int] | None = None
    carrier: str | None = None
    line_type: str | None = None
    area_name: str | None = None
    detected_call_count: int | None = None
    comments: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BusinessListing:
    name: str
    category: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    phone: str
    website: str | None
    source_url: str


@dataclass(frozen=True, slots=True)
class BusinessListingsResult:
    source: str
    number: str
    listings: tuple[BusinessListing, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DocumentFinding:
    title: str
    url: str
    document_type: str
    matched_text: str
    context: str
    confidence: float
    page: int | None = None
    extraction_method: str = "local_text"
    entities: Mapping[str, str] | None = None
    intelligence: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DocumentDiscoveryResult:
    number: str
    queries: tuple[str, ...]
    checked_count: int
    findings: tuple[DocumentFinding, ...]
    failures: tuple[Mapping[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StructuredContactsResult:
    source_url: str
    phones: tuple[Mapping[str, Any], ...]
    emails: tuple[str, ...]
    websites: tuple[str, ...]
    organizations: tuple[str, ...]
    addresses: tuple[str, ...]
    opening_hours: tuple[str, ...]
    structured_sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True, slots=True)
class DomainIntelligenceResult:
    domain: str
    registered: bool | None
    registration_date: str | None
    expiration_date: str | None
    registrar: str | None
    rdap_status: tuple[str, ...]
    ipv4: tuple[str, ...]
    ipv6: tuple[str, ...]
    mx_records: tuple[str, ...]
    mail_configured: bool
    https_valid: bool | None
    certificate_expires: str | None
    certificate_names: tuple[str, ...]
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True, slots=True)
class EmailValidationResult:
    email: str
    syntax_valid: bool
    domain: str | None
    domain_resolves: bool
    mx_configured: bool
    disposable_domain: bool
    deliverability: str
    note: str = "No SMTP connection or email message was sent."

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True, slots=True)
class CompanyRegistryResult:
    source: str
    query: str
    country: str
    count: int
    companies: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True, slots=True)
class DisposableNumberResult:
    number: str
    classification: str
    matched_sources: tuple[Mapping[str, str], ...]
    searched_queries: tuple[str, ...]
    note: str = "Public-directory presence is an indicator, not proof of current number ownership or use."
    checked_sources: tuple[str, ...] = ()
    failures: tuple[Mapping[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]: return asdict(self)
