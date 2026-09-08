from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import phonenumbers

from moriarty.domain.models import BusinessListing, BusinessListingsResult
from moriarty.services.phone_analyzer import PhoneAnalyzer

_URL = "https://telefon.org.tr/"


class TelefonOrgBusinessClient:
    name = "telefon_org_tr"

    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 15.0, loader=None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Source timeout must be greater than zero.")
        self._analyzer, self._timeout = analyzer, timeout_seconds
        self._loader = loader or _load

    def lookup(self, raw_number: str, default_region: str | None = None) -> BusinessListingsResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        parsed = phonenumbers.parse(phone.e164, None)
        if phonenumbers.region_code_for_number(parsed) != "TR":
            return BusinessListingsResult(self.name, phone.e164, ())
        listings: list[BusinessListing] = []
        for record in _records(self._loader(_URL, self._timeout)):
            for displayed in record["phones"]:
                try:
                    matched = self._analyzer.analyze(displayed, "TR").e164 == phone.e164
                except Exception:
                    matched = False
                if matched:
                    listings.append(BusinessListing(
                        name=record["name"], category=record["category"],
                        address=record["address"], latitude=None, longitude=None,
                        phone=displayed, website=None, source_url=_URL,
                    ))
                    break
        return BusinessListingsResult(self.name, phone.e164, tuple(listings))


def _load(url: str, timeout: float) -> str:
    request = Request(url, headers={
        "User-Agent":"Mozilla/5.0 (compatible; Moriarty-V5/0.1; public business lookup)",
        "Accept":"text/html,application/xhtml+xml", "Accept-Language":"tr-TR,tr;q=0.9",
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Telefon.org.tr returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"Telefon.org.tr network error: {exc.reason}") from exc


def _records(html: str) -> tuple[dict[str, object], ...]:
    match = re.search(r"\bconst\s+db\s*=\s*\[", html)
    if not match:
        raise RuntimeError("Telefon.org.tr data block was not found.")
    blocks = _object_blocks(html, match.end())
    records = []
    for block in blocks:
        name = _field(block, "name"); category = _field(block, "cat")
        phones = tuple(_decode(value) for value in re.findall(r'\bnum\s*:\s*"((?:\\.|[^"\\])*)"', block))
        if name and phones:
            records.append({"name":name,"category":category,"address":_field(block,"address"),"phones":phones})
    return tuple(records)


def _field(block: str, key: str) -> str | None:
    match = re.search(rf'\b{re.escape(key)}\s*:\s*"((?:\\.|[^"\\])*)"', block)
    return _decode(match.group(1)) if match else None


def _decode(value: str) -> str:
    return json.loads('"' + value + '"')


def _object_blocks(text: str, start: int) -> tuple[str, ...]:
    blocks=[]; depth=0; begin=None; quoted=False; escaped=False
    for index in range(start, len(text)):
        character=text[index]
        if quoted:
            if escaped: escaped=False
            elif character=="\\": escaped=True
            elif character=='"': quoted=False
            continue
        if character=='"': quoted=True
        elif character=="{":
            if depth==0: begin=index
            depth+=1
        elif character=="}":
            depth-=1
            if depth==0 and begin is not None: blocks.append(text[begin:index+1]);begin=None
        elif character=="]" and depth==0: break
    return tuple(blocks)
