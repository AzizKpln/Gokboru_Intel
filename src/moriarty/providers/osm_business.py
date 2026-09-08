from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import phonenumbers

from moriarty.domain.models import BusinessListing, BusinessListingsResult
from moriarty.services.phone_analyzer import PhoneAnalyzer

_PHONE_KEYS = ("phone", "contact:phone", "mobile", "contact:mobile")
_CATEGORY_KEYS = ("shop", "amenity", "office", "craft", "tourism", "healthcare")


class OsmBusinessClient:
    name = "osm_overpass"

    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 15.0, loader=None, max_results: int = 20) -> None:
        if timeout_seconds <= 0: raise ValueError("Source timeout must be greater than zero.")
        if max_results <= 0: raise ValueError("Maximum results must be greater than zero.")
        self._analyzer, self._timeout_seconds = analyzer, timeout_seconds
        self._loader, self._max_results = loader or _load, max_results

    def lookup(self, raw_number: str, default_region: str | None = None) -> BusinessListingsResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        variants = _variants(phone.e164)
        query = _query(variants, self._timeout_seconds)
        payload = self._loader(query, self._timeout_seconds)
        listings = tuple(_listing(item) for item in payload.get("elements", [])[:self._max_results] if isinstance(item, dict))
        return BusinessListingsResult(self.name, phone.e164, listings)


def _load(query: str, timeout: float) -> dict:
    request = Request(
        "https://overpass-api.de/api/interpreter",
        data=urlencode({"data": query}).encode(),
        headers={"User-Agent": "Moriarty-V5/0.1 (+public business lookup)"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raise RuntimeError(f"OpenStreetMap Overpass returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"OpenStreetMap Overpass network error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenStreetMap Overpass returned invalid JSON.") from exc


def _variants(e164: str) -> tuple[str, ...]:
    number = phonenumbers.parse(e164, None)
    values = (
        e164,
        e164.removeprefix("+"),
        phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
        phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL),
        phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.RFC3966).removeprefix("tel:"),
    )
    return tuple(dict.fromkeys(values))


def _query(variants: tuple[str, ...], timeout: float) -> str:
    key_pattern = "^(" + "|".join(re.escape(key) for key in _PHONE_KEYS) + ")$"
    value_patterns = ("^" + re.escape(value).replace(r"\ ", " ") + "$" for value in variants)
    clauses = [f'nwr[~{json.dumps(key_pattern)}~{json.dumps(pattern)}];' for pattern in value_patterns]
    return f'[out:json][timeout:{max(1, int(timeout))}];(' + "".join(clauses) + ");out center tags;"


def _listing(item: dict) -> BusinessListing:
    tags = item.get("tags") or {}
    center = item.get("center") or {}
    latitude = item.get("lat", center.get("lat"))
    longitude = item.get("lon", center.get("lon"))
    phone = next((str(tags[key]) for key in _PHONE_KEYS if tags.get(key)), "")
    category = next((f"{key}:{tags[key]}" for key in _CATEGORY_KEYS if tags.get(key)), None)
    address_parts = [tags.get(key) for key in ("addr:housenumber", "addr:street", "addr:city", "addr:postcode", "addr:country")]
    address = ", ".join(str(value) for value in address_parts if value) or None
    object_type = str(item.get("type") or "node")
    object_id = item.get("id")
    return BusinessListing(
        name=str(tags.get("name") or tags.get("brand") or tags.get("operator") or "Unnamed business"),
        category=category,
        address=address,
        latitude=float(latitude) if latitude is not None else None,
        longitude=float(longitude) if longitude is not None else None,
        phone=phone,
        website=tags.get("website") or tags.get("contact:website"),
        source_url=f"https://www.openstreetmap.org/{object_type}/{object_id}",
    )
