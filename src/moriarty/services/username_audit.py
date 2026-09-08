from __future__ import annotations

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from moriarty.domain.intelligence_graph import IntelligenceEntity, IntelligenceRelationship
from moriarty.providers.web_username_probe import WEB_PROFILE_SPECS


USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

AUTHORITATIVE_PROFILE_SOURCES = {
    "github", "gitlab", "codeberg", "dockerhub", "reddit", "hackernews",
    "keybase", "bitbucket", "npm", "devto", "lichess", "chesscom",
    "bluesky", "telegram", "gravatar", "roblox",
}


@dataclass(frozen=True, slots=True)
class UsernameSource:
    name: str
    category: str
    description: str


DEFAULT_USERNAME_SOURCES = (
    UsernameSource("github", "developer_profile", "Public GitHub profile metadata."),
    UsernameSource("gitlab", "developer_profile", "Public GitLab profile metadata."),
    UsernameSource("codeberg", "developer_profile", "Public Codeberg profile metadata."),
    UsernameSource("dockerhub", "developer_profile", "Public Docker Hub profile metadata."),
    UsernameSource("reddit", "social_profile", "Public Reddit account metadata."),
    UsernameSource("hackernews", "community_profile", "Public Hacker News account metadata."),
    UsernameSource("keybase", "identity_profile", "Public Keybase profile metadata."),
    UsernameSource("bitbucket", "developer_profile", "Public Bitbucket profile metadata."),
    UsernameSource("npm", "developer_profile", "Public npm account metadata."),
    UsernameSource("devto", "community_profile", "Public DEV Community profile metadata."),
    UsernameSource("lichess", "gaming_profile", "Public Lichess profile metadata."),
    UsernameSource("chesscom", "gaming_profile", "Public Chess.com profile metadata."),
    UsernameSource("bluesky", "social_profile", "Public Bluesky profile metadata."),
    UsernameSource("telegram", "social_profile", "Public Telegram profile preview metadata."),
    UsernameSource("gravatar", "identity_profile", "Public Gravatar profile metadata."),
    UsernameSource("roblox", "gaming_profile", "Public Roblox account metadata."),
    *(UsernameSource(spec.name, spec.category, f"Public {spec.name} profile presence check.") for spec in WEB_PROFILE_SPECS),
    UsernameSource("ahmia", "darkweb_index", "Username mentions in Ahmia's clearnet onion index."),
    UsernameSource("localbreach", "breach_exposure", "Exact username matches in explicitly supplied local datasets."),
    UsernameSource("whatsmyname", "federated_profiles", "Community-maintained exact username checks across hundreds of public sites."),
    UsernameSource("sherlock", "federated_profiles", "Optional local Sherlock checks across public username sites."),
    UsernameSource("maigret", "federated_profiles", "Optional local Maigret profile discovery and public metadata."),
    UsernameSource("socialscan", "social_profile", "Optional local username availability verification for major platforms."),
    UsernameSource("blackbird", "federated_profiles", "Optional independent Blackbird public-profile checks."),
    UsernameSource("gitfive", "developer_intelligence", "Optional GitFive public GitHub profile enrichment."),
    UsernameSource("fediverse", "federated_social", "Public local-account lookups on selected Fediverse instances."),
    UsernameSource("wayback", "historical", "Historical profile captures indexed by the Wayback Machine."),
    UsernameSource("commoncrawl", "historical", "Historical profile URLs indexed by the latest Common Crawl."),
    UsernameSource("breachdirectory", "breach_exposure", "Optional BreachDirectory metadata lookup through its RapidAPI free tier."),
)


class UsernameAuditCore:
    def __init__(self, catalog: Sequence[UsernameSource] = DEFAULT_USERNAME_SOURCES) -> None:
        self.catalog = tuple(catalog)
        self._known = {item.name for item in catalog}

    def run(self, username: str, selected_sources: Sequence[str], runners: Mapping[str, Callable[[], Mapping[str, Any]]]) -> dict[str, Any]:
        username = username.strip()
        if not USERNAME_RE.fullmatch(username):
            raise ValueError("Username must be 1-64 characters and contain only letters, numbers, dot, underscore or hyphen.")
        selected = tuple(dict.fromkeys(item.strip().lower() for item in selected_sources if item.strip()))
        unknown = tuple(item for item in selected if item not in self._known)
        if unknown:
            raise ValueError(f"Unknown username-audit source(s): {', '.join(unknown)}")
        if not selected:
            raise ValueError("Select at least one username-audit source.")
        started_at = datetime.now(timezone.utc)
        started = monotonic()
        target = IntelligenceEntity("username", username, f"@{username}", "target", {"normalized": username.casefold()})
        entities = [target]
        relationships: list[IntelligenceRelationship] = []
        results: list[dict[str, Any]] = []
        def run_source(source: str) -> dict[str, Any]:
            source_started = monotonic()
            try:
                item = dict(runners[source]())
            except Exception as exc:
                item = {"source": source, "status": "provider_error", "profile": None, "note": str(exc) or type(exc).__name__}
            verification_status = str(item.get("status") or "provider_error")
            item["verification_status"] = verification_status
            item["display_status"] = "found" if verification_status == "found" else "not_found"
            item["duration_ms"] = max(0, round((monotonic() - source_started) * 1000))
            return item

        with ThreadPoolExecutor(max_workers=min(8, len(selected)), thread_name_prefix="username-audit") as executor:
            results = list(executor.map(run_source, selected))

        for source, item in zip(selected, results, strict=True):
            profile = item.get("profile")
            if item.get("status") == "found" and isinstance(profile, Mapping):
                profile_url = str(profile.get("html_url") or profile.get("web_url") or f"{source}:{username}")
                label = str(profile.get("name") or profile.get("login") or profile.get("username") or username)
                entity_properties = dict(profile)
                entity_properties["display_status"] = "found"
                entity_properties["verification_status"] = str(item.get("verification_status") or "found")
                confidence = float(item.get("confidence", 1.0))
                entity = IntelligenceEntity("online_profile", profile_url, label, source, entity_properties, confidence)
                entities.append(entity)
                relationships.append(IntelligenceRelationship(target.id, entity.id, "observed_as", source, {"username": username}))
            elif item.get("status") == "found" and isinstance(item.get("matches"), list):
                matches = [match for match in item["matches"] if isinstance(match, Mapping)]
                breach_sources = sorted({str(value) for match in matches for value in (match.get("sources") or []) if value})
                exposed_fields = sorted({str(value) for match in matches for value in (match.get("exposed_fields") or []) if value})
                evidence_urls = list(dict.fromkeys(str(match["evidence_url"]) for match in matches if match.get("evidence_url")))
                record_details = []
                for match in matches[:100]:
                    detail = {key: match.get(key) for key in (
                        "record", "sources", "source_count", "exposed_fields", "password_exposed",
                        "provider_returned_password_mask", "hash_types_observed", "risk", "credential_material_returned",
                        "file", "line_number", "line_sha256", "content_returned", "title", "snippet", "evidence_url",
                    ) if match.get(key) not in (None, "", [], {})}
                    if detail:
                        record_details.append(detail)
                properties = {
                    "display_status": "found", "verification_status": str(item.get("verification_status") or "found"),
                    "match_count": int(item.get("match_count") or len(matches)), "breach_sources": breach_sources,
                    "exposed_fields": exposed_fields, "evidence_urls": evidence_urls[:20],
                    "risk": item.get("risk"), "records": record_details, "data_handling": item.get("data_handling"),
                }
                entity = IntelligenceEntity("exposure_summary", f"{source}:{username}", f"{source} exposure", source, properties, float(item.get("confidence", 0.9)))
                entities.append(entity)
                relationships.append(IntelligenceRelationship(target.id, entity.id, "exposed_in", source))
            if isinstance(item.get("profiles"), list):
                for index, discovered in enumerate(item["profiles"]):
                    if not isinstance(discovered, Mapping):
                        continue
                    profile_url = str(discovered.get("web_url") or f"{source}:{username}:{index}")
                    label = str(discovered.get("name") or discovered.get("username") or username)
                    properties = {**dict(discovered), "display_status": "found", "verification_status": "found"}
                    entity_type = str(discovered.get("entity_type") or "online_profile")
                    confidence = 0.75 if entity_type == "historical_mention" else 0.9
                    entity = IntelligenceEntity(entity_type, profile_url, label, source, properties, confidence)
                    entities.append(entity)
                    relation_type = "historically_observed_as" if entity_type == "historical_mention" else "observed_as"
                    relationships.append(IntelligenceRelationship(target.id, entity.id, relation_type, source, {"username": username, "site": discovered.get("name")}))
        found = sum(item.get("status") == "found" for item in results)
        completed = sum(item.get("verification_status") in {"found", "not_found"} for item in results)
        unverified = len(results) - completed
        completed_at = datetime.now(timezone.utc)
        serialized_entities = [entity.to_dict() for entity in entities]
        correlated_profiles = correlate_username_profiles(serialized_entities)
        return {
            "schema_version": "1.0", "audit_type": "username", "audit_id": str(uuid4()),
            "started_at": started_at.isoformat(), "completed_at": completed_at.isoformat(),
            "duration_ms": max(0, round((monotonic() - started) * 1000)), "username": username,
            "status": "completed" if completed == len(results) else "partial" if completed else "failed",
            "summary": {"requested": len(results), "completed": completed, "found": found, "not_found": sum(item.get("status") == "not_found" for item in results), "unverified": unverified, "failed_or_blocked": unverified},
            "checks": [{"source": item.get("source"), "status": item.get("display_status"), "verification_status": item.get("verification_status")} for item in results],
            "sources": results, "entities": serialized_entities,
            "relationships": [relation.to_dict() for relation in relationships],
            "correlated_profiles": correlated_profiles,
        }


def _canonical_profile_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urllib.parse.urlsplit(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    if host == "twitter.com":
        host = "x.com"
    path = urllib.parse.unquote(parsed.path).rstrip("/").casefold()
    
    
    query = parsed.query if host in {"tagged.com"} else ""
    return urllib.parse.urlunsplit(("https", host, path, query, ""))


def correlate_username_profiles(entities: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate profile entities and attach an explainable confidence tier."""
    grouped: dict[str, dict[str, Any]] = {}
    for entity in entities:
        if entity.get("type") != "online_profile":
            continue
        properties = entity.get("properties") if isinstance(entity.get("properties"), Mapping) else {}
        raw_url = str(properties.get("web_url") or entity.get("value") or "")
        canonical = _canonical_profile_url(raw_url)
        if not canonical:
            continue
        source = str(entity.get("source") or "unknown")
        item = grouped.setdefault(canonical, {
            "url": raw_url, "canonical_url": canonical, "username": properties.get("username"),
            "name": properties.get("name") or entity.get("label"), "bio": properties.get("bio"),
            "avatar_url": properties.get("avatar_url"), "category": properties.get("category"),
            "evidence_sources": [], "source_confidences": [],
        })
        if source not in item["evidence_sources"]:
            item["evidence_sources"].append(source)
        item["source_confidences"].append(float(entity.get("confidence") or 0.0))
        for key in ("username", "name", "bio", "avatar_url", "category"):
            if not item.get(key) and properties.get(key):
                item[key] = properties[key]
    output: list[dict[str, Any]] = []
    for item in grouped.values():
        sources = sorted(item.pop("evidence_sources"))
        confidences = item.pop("source_confidences")
        authoritative = sorted(set(sources) & AUTHORITATIVE_PROFILE_SOURCES)
        independent_count = len(sources)
        if authoritative or independent_count >= 2:
            tier, score = "confirmed", max([0.92, *confidences])
        elif max(confidences, default=0.0) >= 0.85:
            tier, score = "probable", max(confidences)
        else:
            tier, score = "unverified", max(confidences, default=0.5)
        item.update({
            "status": tier, "confidence": round(min(score, 1.0), 2),
            "evidence_sources": sources, "evidence_count": independent_count,
            "authoritative_sources": authoritative,
        })
        output.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
    order = {"confirmed": 0, "probable": 1, "unverified": 2}
    return sorted(output, key=lambda item: (order.get(str(item.get("status")), 9), str(item.get("canonical_url"))))


def compact_username_audit(result: Mapping[str, Any]) -> dict[str, Any]:
    """Human-facing result without graph IDs, repeated edges or empty provider payloads."""
    profiles: list[dict[str, Any]] = []
    breaches: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []
    for entity in result.get("entities", []):
        if not isinstance(entity, Mapping):
            continue
        properties = entity.get("properties") if isinstance(entity.get("properties"), Mapping) else {}
        if entity.get("type") == "exposure_summary":
            breaches.append({key: value for key, value in {
                "source": entity.get("source"), "status": "found", "match_count": properties.get("match_count"),
                "breach_sources": properties.get("breach_sources"), "exposed_fields": properties.get("exposed_fields"),
                "risk": properties.get("risk"), "records": properties.get("records"),
                "evidence_urls": properties.get("evidence_urls"), "data_handling": properties.get("data_handling"),
                "confidence": entity.get("confidence"),
            }.items() if value not in (None, "", [], {})})
        elif entity.get("type") == "historical_mention":
            historical.append({key: value for key, value in {
                "source": entity.get("source"), "archive": properties.get("archive"), "url": properties.get("web_url") or entity.get("value"),
                "original_url": properties.get("original_url"), "captured_at": properties.get("captured_at"), "confidence": entity.get("confidence"),
            }.items() if value not in (None, "", [], {})})
    correlated = result.get("correlated_profiles")
    if isinstance(correlated, list):
        profiles = [dict(item) for item in correlated if isinstance(item, Mapping)]
    else:
        profiles = correlate_username_profiles([item for item in result.get("entities", []) if isinstance(item, Mapping)])
    diagnostics = []
    for item in result.get("sources", []):
        if not isinstance(item, Mapping):
            continue
        status = item.get("verification_status") or item.get("status")
        if status in {"found", "not_found"}:
            continue
        diagnostics.append({key: value for key, value in {"source": item.get("source"), "status": status, "note": item.get("note")}.items() if value})
    summary = dict(result.get("summary") or {})
    summary["profiles_found"] = len(profiles)
    summary["confirmed_profiles"] = sum(item.get("status") == "confirmed" for item in profiles)
    summary["probable_profiles"] = sum(item.get("status") == "probable" for item in profiles)
    summary["unverified_profiles"] = sum(item.get("status") == "unverified" for item in profiles)
    summary["historical_mentions"] = len(historical)
    summary["breach_findings"] = len(breaches)
    return {
        "schema_version": "1.0-compact", "audit_id": result.get("audit_id"), "username": result.get("username"),
        "status": result.get("status"), "summary": summary,
        "findings": {"profiles": profiles, "breaches": breaches, "historical": historical},
        "diagnostics": diagnostics,
    }


def render_username_audit_text(result: Mapping[str, Any], language: str = "tr") -> str:
    """Render a compact username audit as a readable terminal report."""
    tr = language != "en"
    summary = result.get("summary") if isinstance(result.get("summary"), Mapping) else {}
    findings = result.get("findings") if isinstance(result.get("findings"), Mapping) else {}
    profiles = findings.get("profiles") if isinstance(findings.get("profiles"), list) else []
    breaches = findings.get("breaches") if isinstance(findings.get("breaches"), list) else []
    historical = findings.get("historical") if isinstance(findings.get("historical"), list) else []
    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), list) else []
    yes, no, unknown = (("EVET", "HAYIR", "BİLİNMİYOR") if tr else ("YES", "NO", "UNKNOWN"))
    lines = [
        "╔══════════════════════════════════════════════════════════════════════╗",
        "║  GÖKBÖRÜ INTELLIGENCE · " + ("KULLANICI ADI RAPORU" if tr else "USERNAME REPORT").ljust(40) + "║",
        "╚══════════════════════════════════════════════════════════════════════╝",
        f"  {'Hedef' if tr else 'Target'}       : @{result.get('username', '—')}",
        f"  {'Durum' if tr else 'Status'}       : {result.get('status', '—')}",
        f"  {'Kaynaklar' if tr else 'Sources'}     : {summary.get('completed', 0)}/{summary.get('requested', 0)}",
        f"  {'Profiller' if tr else 'Profiles'}    : {len(profiles)}",
        f"  {'İhlâl kayıtları' if tr else 'Breach records'}: {summary.get('breach_findings', len(breaches))}",
    ]

    lines.extend(["", "─" * 72, "  " + ("PROFİLLER" if tr else "PROFILES"), "─" * 72])
    if not profiles:
        lines.append("  " + ("Doğrulanmış profil bulunamadı." if tr else "No verified profiles found."))
    for index, profile in enumerate(profiles[:100], 1):
        if not isinstance(profile, Mapping):
            continue
        url = profile.get("url") or profile.get("web_url") or profile.get("canonical_url") or "—"
        evidence = ", ".join(str(value) for value in profile.get("evidence_sources", []) if value) or "—"
        lines.extend([
            f"  [{index:02}] {profile.get('name') or profile.get('username') or 'Profile'}",
            f"       URL        : {url}",
            f"       {'Güven' if tr else 'Confidence'} : {profile.get('status', 'unverified')} ({round(float(profile.get('confidence') or 0) * 100)}%)",
            f"       {'Kanıt' if tr else 'Evidence'}    : {evidence}",
        ])

    lines.extend(["", "─" * 72, "  " + ("VERİ İHLÂLLERİ" if tr else "DATA BREACHES"), "─" * 72])
    if not breaches:
        lines.append("  " + ("Seçilen kaynaklar doğrulanmış ihlâl kaydı döndürmedi." if tr else "Selected sources returned no verified breach records."))
    breach_index = 0
    for breach in breaches[:100]:
        if not isinstance(breach, Mapping):
            continue
        records = breach.get("records") if isinstance(breach.get("records"), list) else [breach]
        for record in records[:100]:
            if not isinstance(record, Mapping):
                continue
            breach_index += 1
            sources = record.get("sources") or breach.get("breach_sources") or []
            fields = record.get("exposed_fields") or breach.get("exposed_fields") or []
            hashes = record.get("hash_types_observed") or []
            password = record.get("password_exposed")
            password_label = yes if password is True else no if password is False else unknown
            lines.extend([
                f"  [{breach_index:02}] {', '.join(map(str, sources)) or breach.get('source') or 'Breach record'}",
                f"       {'Sağlayıcı' if tr else 'Provider'}   : {breach.get('source') or record.get('provider') or '—'}",
                f"       {'Risk' if tr else 'Risk'}         : {record.get('risk') or breach.get('risk') or 'unknown'}",
                f"       {'Alanlar' if tr else 'Fields'}       : {', '.join(map(str, fields)) or '—'}",
                f"       {'Parola sinyali' if tr else 'Password signal'}: {password_label}",
                f"       {'Hash türleri' if tr else 'Hash types'}  : {', '.join(map(str, hashes)) or '—'}",
            ])
            if record.get("file"):
                lines.append(f"       {'Dosya' if tr else 'File'}        : {record['file']}")
            if record.get("line_number"):
                lines.append(f"       {'Satır' if tr else 'Line'}        : {record['line_number']}")

    lines.extend(["", "─" * 72, "  " + ("GEÇMİŞ KAYITLAR" if tr else "HISTORICAL RECORDS"), "─" * 72])
    if not historical:
        lines.append("  " + ("Geçmiş web kaydı bulunamadı." if tr else "No historical web records found."))
    for index, item in enumerate(historical[:50], 1):
        if isinstance(item, Mapping):
            lines.append(f"  [{index:02}] {item.get('archive') or item.get('source') or 'archive'} · {item.get('captured_at') or '—'}")
            lines.append(f"       {item.get('original_url') or item.get('url') or '—'}")

    if diagnostics:
        lines.extend(["", "─" * 72, "  " + ("KAYNAK DURUMLARI" if tr else "SOURCE STATUSES"), "─" * 72])
        for item in diagnostics[:50]:
            if isinstance(item, Mapping):
                lines.append(f"  • {item.get('source', 'source')}: {item.get('status', 'unverified')} — {item.get('note') or item.get('error') or '—'}")
    return "\n".join(lines)
