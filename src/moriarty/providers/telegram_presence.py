from __future__ import annotations

import os
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from moriarty.services.phone_analyzer import PhoneAnalyzer


class TelegramPresenceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramPresenceResult:
    source: str
    number: str
    status: str
    username: str | None
    display_name: str | None
    profile_url: str | None
    user_id: int | None
    is_bot: bool | None
    is_verified: bool | None
    is_premium: bool | None
    is_fake: bool | None
    is_restricted: bool | None
    mutual_contact: bool | None
    last_seen: str | None
    registered: bool | None
    cached: bool
    cache_age_seconds: int
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TelegramPresenceClient:
    CACHE_TTL_SECONDS = 15 * 60

    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        *,
        api_id: int,
        api_hash: str,
        session_path: str | Path | None = None,
    ) -> None:
        if api_id <= 0 or not api_hash.strip():
            raise TelegramPresenceError("Telegram api_id and api_hash are required.")
        self.analyzer = analyzer
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = Path(
            session_path or Path.home() / ".local/share/moriarty-v5/telegram/moriarty"
        )

    def lookup_own_number(
        self,
        number: str,
        account_number: str,
        region: str | None = None,
    ) -> TelegramPresenceResult:
        target = self.analyzer.analyze(number, region)
        account = self.analyzer.analyze(account_number, region)
        if not target.is_valid or not account.is_valid:
            raise TelegramPresenceError("Valid target and Telegram account numbers are required.")
        if target.e164 != account.e164:
            raise TelegramPresenceError(
                "Self-audit mode requires the queried number to match --telegram-account."
            )
        cached = self._read_cache(target.e164)
        if cached is not None:
            return cached
        try:
            from telethon import functions, types
            from telethon.sync import TelegramClient
        except ImportError as exc:
            raise TelegramPresenceError(
                "Telegram support is not installed. Re-run bash install.sh."
            ) from exc

        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            client = TelegramClient(str(self.session_path), self.api_id, self.api_hash)
            client.start(phone=account.e164)
            try:
                contact = types.InputPhoneContact(
                    client_id=0,
                    phone=target.e164,
                    first_name="Moriarty Self Audit",
                    last_name="",
                )
                imported = client(functions.contacts.ImportContactsRequest([contact]))
                users = tuple(getattr(imported, "users", ()) or ())
                if not users:
                    result = self._unknown(target.e164)
                    self._write_cache(result)
                    return result
                user = users[0]
                
                try:
                    deleted = client(functions.contacts.DeleteContactsRequest(id=[user]))
                    deleted_users = tuple(getattr(deleted, "users", ()) or ())
                    if deleted_users:
                        user = deleted_users[0]
                except Exception as exc:
                    raise TelegramPresenceError(
                        "Telegram returned a user, but the temporary contact could not be removed. "
                        f"Remove it manually before retrying: {exc}"
                    ) from exc
                username = getattr(user, "username", None)
                first = (getattr(user, "first_name", None) or "").strip()
                last = (getattr(user, "last_name", None) or "").strip()
                display_name = " ".join(value for value in (first, last) if value) or None
                result = TelegramPresenceResult(
                    source="telegram_official_client",
                    number=target.e164,
                    status="found",
                    username=username,
                    display_name=display_name,
                    profile_url=f"https://t.me/{username}" if username else None,
                    user_id=getattr(user, "id", None),
                    is_bot=bool(getattr(user, "bot", False)),
                    is_verified=bool(getattr(user, "verified", False)),
                    is_premium=bool(getattr(user, "premium", False)),
                    is_fake=bool(getattr(user, "fake", False)),
                    is_restricted=bool(getattr(user, "restricted", False)),
                    mutual_contact=bool(getattr(user, "mutual_contact", False)),
                    last_seen=self._last_seen(getattr(user, "status", None)),
                    registered=True,
                    cached=False,
                    cache_age_seconds=0,
                    note=(
                        "Telegram returned the user's own account after temporarily importing and then deleting "
                        "the number as a contact. A missing username means there is no public @username."
                    ),
                )
                self._write_cache(result)
                return result
            except TelegramPresenceError:
                raise
            except Exception as exc:
                result = self._telegram_error_result(target.e164, exc)
                if result is None:
                    raise
                return result
            finally:
                client.disconnect()
        except TelegramPresenceError:
            raise
        except Exception as exc:
            raise TelegramPresenceError(f"Telegram lookup failed: {exc}") from exc

    @staticmethod
    def _unknown(number: str) -> TelegramPresenceResult:
        return TelegramPresenceResult(
            "telegram_official_client", number, "unknown", None, None, None, None, None, None,
            None, None, None, None, None, None,
            False, 0,
            "Telegram returned no user. The number may be unregistered or contact discovery may be restricted.",
        )

    
    _not_found = _unknown

    @staticmethod
    def _last_seen(status: Any) -> str | None:
        if status is None:
            return None
        name = type(status).__name__
        labels = {
            "UserStatusOnline": "Currently online",
            "UserStatusRecently": "Last seen recently",
            "UserStatusLastWeek": "Last seen last week",
            "UserStatusLastMonth": "Last seen last month",
            "UserStatusEmpty": "Unknown",
        }
        if name == "UserStatusOffline":
            value = getattr(status, "was_online", None)
            return value.isoformat() if value is not None else "Offline"
        return labels.get(name, "Unknown")

    @staticmethod
    def _telegram_error_result(number: str, exc: Exception) -> TelegramPresenceResult | None:
        text = str(exc)
        lowered = text.lower()
        error_name = type(exc).__name__.lower()
        if "frozen" in lowered or "frozen" in error_name or "banned" in error_name:
            status = "account_restricted"
            note = "The querying Telegram account is frozen, banned, or restricted from importing contacts."
        elif "flood" in error_name or "wait of" in lowered or "too many requests" in lowered:
            status = "rate_limited"
            seconds = getattr(exc, "seconds", None)
            note = "Telegram rate-limited this account."
            if seconds is not None:
                note += f" Retry after at least {int(seconds)} seconds."
        else:
            return None
        return TelegramPresenceResult(
            "telegram_official_client", number, status, None, None, None, None, None, None,
            None, None, None, None, None, None, False, 0, note,
        )

    @property
    def cache_path(self) -> Path:
        return self.session_path.with_suffix(".presence-cache.json")

    def _read_cache(self, number: str) -> TelegramPresenceResult | None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            cached_at = float(payload["cached_at"])
            age = max(0, int(time.time() - cached_at))
            data = dict(payload["result"])
            if age >= self.CACHE_TTL_SECONDS or data.get("number") != number:
                return None
            data["cached"] = True
            data["cache_age_seconds"] = age
            return TelegramPresenceResult(**data)
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def _write_cache(self, result: TelegramPresenceResult) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"cached_at": time.time(), "result": result.to_dict()}
        temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(self.cache_path)
        try:
            os.chmod(self.cache_path, 0o600)
        except OSError:
            pass


def telegram_credentials(api_id: int | None, api_hash: str | None) -> tuple[int, str]:
    raw_id = str(api_id or os.getenv("TELEGRAM_API_ID", "")).strip()
    resolved_hash = (api_hash or os.getenv("TELEGRAM_API_HASH", "")).strip()
    try:
        resolved_id = int(raw_id)
    except ValueError as exc:
        raise TelegramPresenceError("Set TELEGRAM_API_ID to the numeric api_id from my.telegram.org.") from exc
    if resolved_id <= 0 or not resolved_hash:
        raise TelegramPresenceError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH from my.telegram.org.")
    return resolved_id, resolved_hash
