from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Mapping
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from moriarty.services.phone_analyzer import PhoneAnalyzer


class TruecallerConsentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TruecallerConsentRequest:
    expected_number: str
    request_id: str
    deep_link: str
    platform: str = "android_mobile_web"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TruecallerProfile:
    expected_number: str
    verified_number: str
    number_matches: bool
    display_name: str | None
    first_name: str | None
    last_name: str | None
    profile_type: str | None
    badges: tuple[str, ...]
    city: str | None
    country_code: str | None
    company_name: str | None
    job_title: str | None
    source: str = "truecaller_user_consent"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_consent_request(
    analyzer: PhoneAnalyzer,
    number: str,
    app_key: str,
    app_name: str,
    *,
    region: str | None = None,
    privacy_url: str | None = None,
    terms_url: str | None = None,
    ttl_ms: int = 120_000,
    request_id: str | None = None,
) -> TruecallerConsentRequest:
    expected = analyzer.analyze(number, region).e164
    if not app_key.strip():
        raise TruecallerConsentError("TRUECALLER_APP_KEY is required.")
    if not app_name.strip():
        raise TruecallerConsentError("Truecaller partner/app name is required.")
    if ttl_ms < 8_000:
        raise TruecallerConsentError("Truecaller consent TTL must be at least 8000 ms.")

    nonce = request_id or secrets.token_urlsafe(24)
    if not 8 <= len(nonce) <= 64:
        raise TruecallerConsentError("Truecaller request id must be 8-64 characters.")

    params = {
        "type": "btmsheet",
        "requestNonce": nonce,
        "partnerKey": app_key.strip(),
        "partnerName": app_name.strip(),
        "lang": "en",
        "loginPrefix": "continue",
        "loginSuffix": "verifymobile",
        "ctaPrefix": "continuewith",
        "ctaColor": "#5b45e0",
        "ctaTextColor": "#ffffff",
        "btnShape": "round",
        "skipOption": "useanothermethod",
        "ttl": str(ttl_ms),
    }
    if privacy_url:
        params["privacyUrl"] = _https_url(privacy_url, "privacy URL")
    if terms_url:
        params["termsUrl"] = _https_url(terms_url, "terms URL")
    return TruecallerConsentRequest(
        expected_number=expected,
        request_id=nonce,
        deep_link="truecallersdk://truesdk/web_verify?" + urlencode(params),
    )


def consume_callback(
    analyzer: PhoneAnalyzer,
    expected_number: str,
    expected_request_id: str,
    callback: Mapping[str, Any],
    *,
    region: str | None = None,
    timeout_seconds: float = 10.0,
) -> TruecallerProfile:
    if callback.get("requestId") != expected_request_id:
        raise TruecallerConsentError("Truecaller callback request id does not match.")
    if callback.get("status") == "user_rejected":
        raise TruecallerConsentError("The user rejected the Truecaller consent request.")
    access_token = str(callback.get("accessToken") or "").strip()
    endpoint = str(callback.get("endpoint") or "").strip()
    if not access_token or not endpoint:
        raise TruecallerConsentError("Truecaller callback has no profile access token or endpoint.")
    _truecaller_endpoint(endpoint)
    request = Request(
        endpoint,
        headers={"Authorization": f"Bearer {access_token}", "Cache-Control": "no-cache"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise TruecallerConsentError(f"Truecaller profile request failed: {exc}") from exc
    return profile_from_payload(analyzer, expected_number, payload, region=region)


def profile_from_payload(
    analyzer: PhoneAnalyzer,
    expected_number: str,
    payload: Mapping[str, Any],
    *,
    region: str | None = None,
) -> TruecallerProfile:
    expected = analyzer.analyze(expected_number, region).e164
    candidates = payload.get("phoneNumbers")
    if not isinstance(candidates, list) or not candidates:
        raise TruecallerConsentError("Truecaller profile did not contain a phone number.")
    raw_number = str(candidates[0]).strip()
    if not raw_number.startswith("+"):
        raw_number = "+" + raw_number
    verified = analyzer.analyze(raw_number, None).e164
    if verified != expected:
        raise TruecallerConsentError("Consented Truecaller profile belongs to a different number.")

    name = payload.get("name") if isinstance(payload.get("name"), Mapping) else {}
    first = _text(name.get("first"))
    last = _text(name.get("last"))
    display = " ".join(part for part in (first, last) if part) or None
    addresses = payload.get("addresses") if isinstance(payload.get("addresses"), list) else []
    address = addresses[0] if addresses and isinstance(addresses[0], Mapping) else {}
    badges = payload.get("badges") if isinstance(payload.get("badges"), list) else []
    return TruecallerProfile(
        expected_number=expected,
        verified_number=verified,
        number_matches=True,
        display_name=display,
        first_name=first,
        last_name=last,
        profile_type=_text(payload.get("type")),
        badges=tuple(str(item) for item in badges),
        city=_text(address.get("city")),
        country_code=_text(address.get("countryCode")),
        company_name=_text(payload.get("companyName")),
        job_title=_text(payload.get("jobTitle")),
    )


def _truecaller_endpoint(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "truecaller.com" or host.endswith(".truecaller.com")):
        raise TruecallerConsentError("Truecaller supplied an invalid profile endpoint.")
    return value


def _https_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise TruecallerConsentError(f"Truecaller {label} must be a public HTTPS URL.")
    return value


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
