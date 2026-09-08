from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from .services.phone_audit import DEFAULT_PHONE_AUDIT_SOURCES
from .services.username_audit import DEFAULT_USERNAME_SOURCES
from .providers.gemini_case_analysis import GeminiCaseAnalysis
from .providers.search_backend import SearchBackendError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SOURCE_LABELS = {
    "local": "Numara ve operatör", "truecaller": "Truecaller", "syncme": "Sync.me",
    "telegram": "Telegram", "facebook": "Facebook", "whatsapp": "WhatsApp",
    "cybernews": "Cybernews", "databreach": "DataBreach", "hudsonrock": "Hudson Rock",
    "github": "GitHub", "reddit": "Reddit", "brave": "Brave Search",
    "duckduckgo": "DuckDuckGo", "web-mentions": "Açık web", "pastebin": "Pastebin",
    "documents": "PDF ve belgeler", "reputation": "Numara şikâyetleri",
    "business": "İşletme kayıtları", "disposable": "Geçici SMS servisleri",
    "opensanctions": "OpenSanctions", "ftc": "FTC şikâyetleri",
    "btk": "BTK operatör sorgusu",
}


def source_catalog() -> list[dict[str, Any]]:
    return [{
        "id": item.name, "label": SOURCE_LABELS.get(item.name, item.name),
        "category": item.category, "description": item.description,
        "requirements": list(item.requires_configuration),
    } for item in DEFAULT_PHONE_AUDIT_SOURCES]


def username_source_catalog() -> list[dict[str, Any]]:
    requirements = {"breachdirectory": ["BREACHDIRECTORY_API_KEY"], "localbreach": ["local breach path"]}
    return [{"id": item.name, "label": item.name.replace("_", " ").title(), "category": item.category, "description": item.description, "requirements": requirements.get(item.name, [])} for item in DEFAULT_USERNAME_SOURCES]


SECRET_KEYS = {"telegram_api_hash", "gemini_api_key", "brave_api_key", "github_token", "hudsonrock_api_key", "opensanctions_api_key", "breachdirectory_api_key", "microsoft_email", "microsoft_password"}


@dataclass
class ConfigurationStore:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def public(self) -> dict[str, Any]:
        value = self.effective()
        public = {key: item for key, item in value.items() if key not in SECRET_KEYS}
        public["configured"] = {key: bool(value.get(key)) for key in SECRET_KEYS}
        public["ready"] = bool(value.get("setup_complete"))
        return public

    def effective(self) -> dict[str, Any]:
        value = self.load()
        environment = {
            "telegram_api_id":"TELEGRAM_API_ID", "telegram_api_hash":"TELEGRAM_API_HASH",
            "telegram_account":"TELEGRAM_ACCOUNT", "gemini_api_key":"GEMINI_API_KEY",
            "brave_api_key":"BRAVE_SEARCH_API_KEY", "github_token":"GITHUB_TOKEN",
            "hudsonrock_api_key":"HUDSONROCK_API_KEY", "opensanctions_api_key":"OPENSANCTIONS_API_KEY",
            "breachdirectory_api_key":"BREACHDIRECTORY_API_KEY",
            "microsoft_email":"GOKBORU_MICROSOFT_EMAIL", "microsoft_password":"GOKBORU_MICROSOFT_PASSWORD",
        }
        for key, name in environment.items():
            if not value.get(key) and os.environ.get(name):
                value[key] = os.environ[name]
        return value

    def save(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        current = self.load()
        allowed = SECRET_KEYS | {"telegram_api_id", "telegram_account", "telegram_session_path", "truecaller_profile_dir", "syncme_profile_dir", "language", "setup_complete"}
        for key in allowed:
            if key not in payload:
                continue
            value = payload[key]
            if key in SECRET_KEYS and value in {"", None, "********"}:
                continue
            current[key] = value
        current["setup_complete"] = True
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return self.public()


def run_phone_audit(payload: Mapping[str, Any], configuration: Mapping[str, Any]) -> dict[str, Any]:
    number = str(payload.get("number") or "").strip()
    requested = payload.get("sources")
    allowed = {item.name for item in DEFAULT_PHONE_AUDIT_SOURCES}
    if not number:
        raise ValueError("Telefon numarası gerekli.")
    if not isinstance(requested, list) or not requested:
        raise ValueError("En az bir kaynak seçin.")
    sources = [str(item) for item in requested if str(item) in allowed]
    if len(sources) != len(requested):
        raise ValueError("Geçersiz kaynak seçimi.")
    command = [sys.executable, "-m", "moriarty.web_phone_audit_entry", number,
               "--sources", ",".join(sources), "--i-own-this-number",
               "--timeout", str(max(10, min(300, int(payload.get("timeout") or 60))))]
    region = str(payload.get("region") or "").strip().upper()
    if region:
        command.extend(["--region", region])
    option_map = {
        "telegram_api_id": "--telegram-api-id",
        "telegram_api_hash": "--telegram-api-hash", "telegram_session_path": "--telegram-session-path",
        "truecaller_profile_dir": "--truecaller-profile-dir", "syncme_profile_dir": "--syncme-profile-dir",
    }
    for key, option in option_map.items():
        if configuration.get(key) not in {None, ""}:
            command.extend([option, str(configuration[key])])
    if "telegram" in sources:
        command.extend(["--telegram-account", number])
    hidden_browser = bool(payload.get("hidden_browser", True))
    if hidden_browser:
        
        
        command.append("--headless")
    env = os.environ.copy()
    env_map = {"gemini_api_key":"GEMINI_API_KEY", "brave_api_key":"BRAVE_SEARCH_API_KEY", "github_token":"GITHUB_TOKEN", "hudsonrock_api_key":"HUDSONROCK_API_KEY", "opensanctions_api_key":"OPENSANCTIONS_API_KEY", "microsoft_email":"GOKBORU_MICROSOFT_EMAIL", "microsoft_password":"GOKBORU_MICROSOFT_PASSWORD"}
    for key, name in env_map.items():
        if configuration.get(key):
            env[name] = str(configuration[key])
    process = subprocess.run(command, capture_output=True, text=True, env=env,
                             stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
                             timeout=max(90, len(sources) * (max(10, min(300, int(payload.get("timeout") or 60))) + 20) + 30), check=False)
    output = process.stdout.strip()
    if not output:
        detail = process.stderr.strip()
        raise ValueError(
            f"Araştırma sonuç üretmeden sonlandı (çıkış kodu: {process.returncode})."
            + (f" Ayrıntı: {detail[-2000:]}" if detail else "")
        )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        detail = process.stderr.strip()
        raise ValueError(
            "Araştırma sonucu JSON olarak okunamadı."
            + (f" Ayrıntı: {detail[-2000:]}" if detail else f" Çıktı: {output[-1000:]}")
        ) from exc
    if process.returncode and isinstance(result, Mapping) and result.get("error"):
        raise ValueError(str(result["error"]))
    return dict(result)


def run_username_audit(payload: Mapping[str, Any], configuration: Mapping[str, Any]) -> dict[str, Any]:
    username = str(payload.get("username") or "").strip()
    requested = payload.get("sources")
    allowed = {item.name for item in DEFAULT_USERNAME_SOURCES}
    if not username:
        raise ValueError("Kullanıcı adı gerekli.")
    if not isinstance(requested, list) or not requested:
        raise ValueError("En az bir kullanıcı adı kaynağı seçin.")
    sources = [str(item) for item in requested if str(item) in allowed]
    if len(sources) != len(requested):
        raise ValueError("Geçersiz kullanıcı adı kaynağı seçimi.")
    timeout = max(10, min(60, int(payload.get("timeout") or 45)))
    command = [sys.executable, "-m", "moriarty", "username-audit", username, "--sources", ",".join(sources), "--timeout", str(timeout), "--wmn-limit", "180", "--exposure-limit", "20", "--full-json"]
    if configuration.get("github_token"):
        command.extend(["--github-token", str(configuration["github_token"])])
    if configuration.get("breachdirectory_api_key"):
        command.extend(["--breachdirectory-key", str(configuration["breachdirectory_api_key"])])
    process = subprocess.run(command, capture_output=True, text=True, env=os.environ.copy(), timeout=timeout + 75, check=False)
    if not process.stdout.strip():
        raise ValueError("Kullanıcı adı araştırması sonuç üretmedi." + (f" Ayrıntı: {process.stderr[-1500:]}" if process.stderr else ""))
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Kullanıcı adı araştırması JSON olarak okunamadı.") from exc
    if result.get("error"):
        raise ValueError(str(result["error"]))
    categories = {item.name: item.category for item in DEFAULT_USERNAME_SOURCES}
    correlated = result.get("correlated_profiles") if isinstance(result.get("correlated_profiles"), list) else []
    web_sources = []
    for item in result.get("sources", []):
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("source") or "unknown")
        
        
        profiles = [profile for profile in correlated if isinstance(profile, Mapping) and (profile.get("evidence_sources") or [None])[0] == name]
        raw_profiles = item.get("profiles") if isinstance(item.get("profiles"), list) else []
        historical_mentions = [entry for entry in raw_profiles if isinstance(entry, Mapping) and entry.get("entity_type") == "historical_mention"]
        matches = item.get("matches") if isinstance(item.get("matches"), list) else []
        data = {key: value for key, value in {
            "source": name, "status": item.get("status"), "note": item.get("note"),
            "checked_count": item.get("checked_count"), "found_count": item.get("found_count"),
            "match_count": item.get("match_count"), "risk": item.get("risk"),
            "profiles": profiles, "matches": matches[:50], "mentions": historical_mentions[:30],
        }.items() if value not in (None, "", [], {})}
        verified = item.get("verification_status")
        if verified == "not_found":
            continue
        web_sources.append({
            "source": name, "category": categories.get(name, "username_profile"),
            "state": "completed" if verified in {"found", "not_found"} else "failed",
            "finding": "finding" if verified == "found" else "clear" if verified == "not_found" else "indeterminate",
            "provider_status": verified, "duration_ms": item.get("duration_ms"), "data": data,
            "error": item.get("note") if verified not in {"found", "not_found"} else None,
        })
    result["sources"] = web_sources
    result["audit_type"] = "username"
    result["web_optimization"] = {
        "profiles_stored_once": len(correlated), "empty_sources_suppressed": True,
        "raw_graph_entities_suppressed": len(result.get("entities") or []),
    }
    result.pop("entities", None)
    result.pop("relationships", None)
    result.pop("correlated_profiles", None)
    return result


@dataclass
class InvestigationStore:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._compact_username_case(item) for item in self._load().get("investigations", [])]

    @staticmethod
    def _compact_username_case(investigation: Mapping[str, Any]) -> dict[str, Any]:
        audits = investigation.get("audits") if isinstance(investigation.get("audits"), list) else []
        if not any(isinstance(audit, Mapping) and audit.get("audit_type") == "username" for audit in audits):
            return dict(investigation)
        clean = json.loads(json.dumps(investigation, ensure_ascii=False))
        unique_profiles: dict[str, dict[str, Any]] = {}
        breaches: list[dict[str, Any]] = []
        mentions: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for source in clean.get("sources", []):
            if not isinstance(source, Mapping):
                continue
            data = source.get("data") if isinstance(source.get("data"), Mapping) else {}
            for profile in data.get("profiles", []):
                if isinstance(profile, Mapping):
                    key = str(profile.get("canonical_url") or profile.get("url") or profile.get("web_url") or "")
                    if key: unique_profiles[key] = dict(profile)
            for mention in data.get("mentions", []):
                if isinstance(mention, Mapping) and len(mentions) < 60: mentions.append(dict(mention))
            for match in data.get("matches", []):
                if isinstance(match, Mapping) and len(breaches) < 100:
                    breaches.append({**dict(match), "provider": source.get("source")})
            if source.get("state") == "failed" or source.get("finding") == "indeterminate":
                diagnostics.append({"source": source.get("source"), "status": source.get("provider_status"), "error": source.get("error")})
        for audit in audits:
            if not isinstance(audit, Mapping):
                continue
            findings = audit.get("findings") if isinstance(audit.get("findings"), Mapping) else {}
            for breach in findings.get("breaches", []):
                if isinstance(breach, Mapping) and len(breaches) < 100:
                    summary = dict(breach)
                    records = summary.pop("records", [])
                    if isinstance(records, list) and records:
                        for record in records:
                            if isinstance(record, Mapping) and len(breaches) < 100:
                                breaches.append({**dict(record), "provider": summary.get("source"), "summary": summary})
                    else:
                        breaches.append({**summary, "provider": summary.get("source")})
        compact_sources = [{
            "source": "username-results", "category": "federated_profiles", "state": "completed",
            "finding": "finding" if unique_profiles else "clear", "provider_status": "success",
            "data": {"profiles": list(unique_profiles.values()), "profile_count": len(unique_profiles)},
        }]
        if mentions:
            compact_sources.append({"source": "username-history", "category": "historical", "state": "completed", "finding": "finding", "provider_status": "success", "data": {"mentions": mentions, "mention_count": len(mentions)}})
        if breaches:
            compact_sources.append({"source": "username-breaches", "category": "breach_exposure", "state": "completed", "finding": "finding", "provider_status": "success", "data": {"matches": breaches, "match_count": len(breaches)}})
        if diagnostics:
            compact_sources.append({"source": "username-diagnostics", "category": "federated_profiles", "state": "completed", "finding": "indeterminate", "provider_status": "partial", "data": {"diagnostics": diagnostics[:50]}})
        clean["sources"] = compact_sources
        for audit in clean.get("audits", []):
            if isinstance(audit, dict) and audit.get("audit_type") == "username":
                audit.pop("entities", None); audit.pop("relationships", None); audit.pop("correlated_profiles", None); audit.pop("sources", None)
        return clean

    def get(self, investigation_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list() if item.get("id") == investigation_id), None)

    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "Yeni Soruşturma").strip()[:120]
        subject = str(payload.get("subject") or "").strip()[:120]
        now = _now()
        investigation = {
            "id": str(uuid4()), "title": title, "subject": subject,
            "status": "active", "priority": str(payload.get("priority") or "normal"),
            "notes": str(payload.get("notes") or "")[:5000],
            "created_at": now, "updated_at": now, "audits": [], "sources": [],
            "summary": {"audits": 0, "sources": 0, "findings": 0, "clear": 0, "blocked": 0, "failed": 0},
        }
        with self._lock:
            database = self._load()
            database.setdefault("investigations", []).insert(0, investigation)
            self._save(database)
        return investigation

    def add_audit(self, investigation_id: str, audit: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(audit.get("sources"), list):
            raise ValueError("Geçerli bir denetim JSON çıktısı gerekli: sources listesi bulunamadı.")
        with self._lock:
            database = self._load()
            investigation = next((item for item in database.get("investigations", []) if item.get("id") == investigation_id), None)
            if investigation is None:
                raise KeyError(investigation_id)
            clean_audit = json.loads(json.dumps(audit, ensure_ascii=False))
            clean_audit.setdefault("audit_id", str(uuid4()))
            clean_audit["imported_at"] = _now()
            investigation.setdefault("audits", []).append(clean_audit)
            investigation["sources"] = self._merge_sources(investigation["audits"])
            investigation["summary"] = self._summary(investigation["audits"], investigation["sources"])
            investigation["updated_at"] = _now()
            self._save(database)
            self._export(investigation)
            return investigation

    def delete(self, investigation_id: str) -> bool:
        with self._lock:
            database = self._load()
            before = len(database.get("investigations", []))
            database["investigations"] = [item for item in database.get("investigations", []) if item.get("id") != investigation_id]
            if len(database["investigations"]) == before:
                return False
            self._save(database)
            return True

    def set_analysis(self, investigation_id: str, analysis: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            database = self._load()
            investigation = next((item for item in database.get("investigations", []) if item.get("id") == investigation_id), None)
            if investigation is None:
                raise KeyError(investigation_id)
            investigation["analysis"] = json.loads(json.dumps(analysis, ensure_ascii=False))
            investigation["updated_at"] = _now()
            self._save(database)
            self._export(investigation)
            return investigation

    def _export(self, investigation: Mapping[str, Any]) -> None:
        export_dir = self.path.parent / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        target = export_dir / f"{investigation.get('id', 'investigation')}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(investigation, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)

    @staticmethod
    def _merge_sources(audits: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for audit in audits:
            for source in audit.get("sources", []):
                if not isinstance(source, Mapping):
                    continue
                name = str(source.get("source") or "unknown")
                entry = json.loads(json.dumps(source, ensure_ascii=False))
                entry["audit_id"] = audit.get("audit_id")
                entry["observed_at"] = audit.get("completed_at") or audit.get("imported_at")
                previous = merged.get(name)
                if previous is None or str(entry.get("observed_at") or "") >= str(previous.get("observed_at") or ""):
                    merged[name] = entry
        return sorted(merged.values(), key=lambda item: (str(item.get("category") or ""), str(item.get("source") or "")))

    @staticmethod
    def _summary(audits: list[Mapping[str, Any]], sources: list[Mapping[str, Any]]) -> dict[str, int]:
        return {
            "audits": len(audits), "sources": len(sources),
            "findings": sum(item.get("finding") == "finding" for item in sources),
            "clear": sum(item.get("finding") == "clear" for item in sources),
            "blocked": sum(item.get("state") == "blocked" for item in sources),
            "failed": sum(item.get("state") == "failed" for item in sources),
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": "1.0", "investigations": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": "1.0", "investigations": []}
        return payload if isinstance(payload, dict) else {"schema_version": "1.0", "investigations": []}

    def _save(self, payload: Mapping[str, Any]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def serve_workspace(host: str = "127.0.0.1", port: int = 8765, data_dir: str | Path | None = None, open_browser: bool = True) -> None:
    root = Path(__file__).with_name("web_static")
    store_path = Path(data_dir or Path.home() / ".local/share/moriarty-v5/gokboru") / "investigations.json"
    store = InvestigationStore(store_path)
    configuration = ConfigurationStore(store_path.with_name("configuration.json"))

    class Handler(BaseHTTPRequestHandler):
        server_version = "GokboruIntelligence/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/health":
                return self._json({"status": "ok", "service": "gokboru-intelligence"})
            if path == "/api/investigations":
                return self._json({"investigations": store.list()})
            if path == "/api/sources":
                return self._json({"sources": source_catalog()})
            if path == "/api/username-sources":
                return self._json({"sources": username_source_catalog()})
            if path == "/api/config":
                return self._json(configuration.public())
            if path == "/api/media":
                requested = parse_qs(parsed.query).get("path", [""])[0]
                allowed: set[str] = set()
                def collect(value: Any) -> None:
                    if isinstance(value, Mapping):
                        for key, item in value.items():
                            if key == "photo_path" and isinstance(item, str):
                                allowed.add(str(Path(item).resolve()))
                            else:
                                collect(item)
                    elif isinstance(value, list):
                        for item in value:
                            collect(item)
                collect(store.list())
                candidate = str(Path(requested).resolve()) if requested else ""
                if candidate not in allowed or not Path(candidate).is_file():
                    return self._json({"error": "Görsel bulunamadı."}, HTTPStatus.NOT_FOUND)
                body = Path(candidate).read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mimetypes.guess_type(candidate)[0] or "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "private, max-age=300")
                self.end_headers(); self.wfile.write(body); return
            if path == "/api/photo-proxy":
                requested = parse_qs(parsed.query).get("url", [""])[0]
                allowed: set[str] = set()
                def collect_urls(value: Any) -> None:
                    if isinstance(value, Mapping):
                        for key, item in value.items():
                            if key == "photo_url" and isinstance(item, str):
                                allowed.add(item)
                            else:
                                collect_urls(item)
                    elif isinstance(value, list):
                        for item in value:
                            collect_urls(item)
                collect_urls(store.list())
                parsed_photo = urlparse(requested)
                if requested not in allowed or parsed_photo.scheme != "https" or not parsed_photo.hostname or not parsed_photo.hostname.endswith("facebook.com"):
                    return self._json({"error": "Görsel bağlantısına izin verilmedi."}, HTTPStatus.FORBIDDEN)
                try:
                    request = Request(requested, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*"})
                    with urlopen(request, timeout=20) as response:
                        body = response.read(8_000_000)
                        content_type = response.headers.get_content_type()
                    if not content_type.startswith("image/"):
                        return self._json({"error": "Facebook görsel döndürmedi."}, HTTPStatus.BAD_GATEWAY)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "private, max-age=3600")
                    self.end_headers(); self.wfile.write(body); return
                except Exception:
                    return self._json({"error": "Facebook görseli alınamadı."}, HTTPStatus.BAD_GATEWAY)
            if path.startswith("/api/investigations/"):
                item = store.get(unquote(path.rsplit("/", 1)[-1]))
                return self._json(item or {"error": "Soruşturma bulunamadı."}, HTTPStatus.OK if item else HTTPStatus.NOT_FOUND)
            return self._static(path, root)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                payload = self._body()
                if path == "/api/investigations":
                    return self._json(store.create(payload), HTTPStatus.CREATED)
                if path == "/api/search":
                    if not configuration.public().get("ready"):
                        raise ValueError("İlk kurulum tamamlanmadan araştırma başlatılamaz.")
                    result = run_phone_audit(payload, configuration.effective())
                    investigation = store.create({
                        "title": str(payload.get("title") or result.get("number") or "Telefon araştırması"),
                        "subject": result.get("number") or payload.get("number"),
                        "priority": "normal", "notes": "Web çalışma alanından oluşturuldu.",
                    })
                    return self._json(store.add_audit(investigation["id"], result), HTTPStatus.CREATED)
                if path == "/api/username-search":
                    if not configuration.public().get("ready"):
                        raise ValueError("İlk kurulum tamamlanmadan araştırma başlatılamaz.")
                    result = run_username_audit(payload, configuration.effective())
                    investigation = store.create({
                        "title": str(payload.get("title") or f"@{result.get('username')}"),
                        "subject": result.get("username") or payload.get("username"),
                        "priority": "normal", "notes": "Web çalışma alanından kullanıcı adı araştırması.",
                    })
                    return self._json(store.add_audit(investigation["id"], result), HTTPStatus.CREATED)
                if path == "/api/config":
                    return self._json(configuration.save(payload), HTTPStatus.OK)
                if path.endswith("/audits") and path.startswith("/api/investigations/"):
                    investigation_id = unquote(path.split("/")[-2])
                    return self._json(store.add_audit(investigation_id, payload), HTTPStatus.CREATED)
                if path.endswith("/analysis") and path.startswith("/api/investigations/"):
                    investigation_id = unquote(path.split("/")[-2])
                    investigation = store.get(investigation_id)
                    if investigation is None:
                        raise KeyError(investigation_id)
                    analyzer = GeminiCaseAnalysis(api_key=configuration.effective().get("gemini_api_key"))
                    analysis = analyzer.analyze(investigation, language="tr" if payload.get("language") == "tr" else "en")
                    return self._json(store.set_analysis(investigation_id, analysis), HTTPStatus.OK)
                self._json({"error": "Bilinmeyen uç nokta."}, HTTPStatus.NOT_FOUND)
            except KeyError:
                self._json({"error": "Soruşturma bulunamadı."}, HTTPStatus.NOT_FOUND)
            except (ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except subprocess.TimeoutExpired:
                self._json({"error": "Araştırma zaman sınırını aştı. Daha az kaynak seçerek yeniden deneyin."}, HTTPStatus.REQUEST_TIMEOUT)
            except SearchBackendError as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)

        def do_DELETE(self) -> None:
            path = urlparse(self.path).path
            if path.startswith("/api/investigations/"):
                deleted = store.delete(unquote(path.rsplit("/", 1)[-1]))
                return self._json({"deleted": deleted}, HTTPStatus.OK if deleted else HTTPStatus.NOT_FOUND)
            self._json({"error": "Bilinmeyen uç nokta."}, HTTPStatus.NOT_FOUND)

        def _body(self) -> Mapping[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 10_000_000:
                raise ValueError("JSON dosyası 10 MB sınırını aşıyor.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("JSON nesnesi gerekli.")
            return payload

        def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

        def _static(self, path: str, static_root: Path) -> None:
            relative = "index.html" if path in {"", "/"} else path.lstrip("/")
            candidate = (static_root / relative).resolve()
            if static_root.resolve() not in candidate.parents and candidate != static_root.resolve():
                return self._json({"error": "Geçersiz yol."}, HTTPStatus.BAD_REQUEST)
            if not candidate.is_file():
                candidate = static_root / "index.html"
            body = candidate.read_bytes()
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") or "javascript" in content_type else content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers(); self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_port}/"
    print(f"Gökbörü Intelligence çalışma alanı: {url}")
    print(f"Yerel veri deposu: {store_path}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
