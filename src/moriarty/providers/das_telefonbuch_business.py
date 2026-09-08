from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import phonenumbers

from moriarty.domain.models import BusinessListing, BusinessListingsResult
from moriarty.services.phone_analyzer import PhoneAnalyzer

_URL = "https://www.dastelefonbuch.de/R%C3%BCckw%C3%A4rts-Suche"


class DasTelefonbuchBusinessClient:
    name = "das_telefonbuch_de"

    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 15.0, loader=None, max_results: int = 20) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Source timeout must be greater than zero.")
        if max_results <= 0:
            raise ValueError("Maximum results must be greater than zero.")
        self._analyzer, self._timeout = analyzer, timeout_seconds
        self._loader, self._max_results = loader or _load, max_results

    def lookup(self, raw_number: str, default_region: str | None = None) -> BusinessListingsResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        parsed = phonenumbers.parse(phone.e164, None)
        if phonenumbers.region_code_for_number(parsed) != "DE":
            return BusinessListingsResult(self.name, phone.e164, ())
        national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
        _, html = self._loader(_URL, {"stype":"RBP","mode":"search","phone":national}, self._timeout)
        parser = _HitParser(); parser.feed(html); parser.finish()
        listings = tuple(
            listing for listing in (_listing(row) for row in parser.rows)
            if listing is not None and _normalizes_to(listing.phone, phone.e164, self._analyzer)
        )[:self._max_results]
        return BusinessListingsResult(self.name, phone.e164, listings)


def _load(url: str, fields: dict[str,str], timeout: float) -> tuple[str,str]:
    request = Request(url, data=urlencode(fields).encode(), headers={
        "User-Agent":"Mozilla/5.0 (compatible; Moriarty-V5/0.1; public business lookup)",
        "Content-Type":"application/x-www-form-urlencoded",
        "Accept":"text/html,application/xhtml+xml", "Accept-Language":"de-DE,de;q=0.9,en;q=0.7",
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.geturl(), response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Das Telefonbuch returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"Das Telefonbuch network error: {exc.reason}") from exc


def _normalizes_to(value: str, expected: str, analyzer: PhoneAnalyzer) -> bool:
    try: return analyzer.analyze(value, "DE").e164 == expected
    except Exception: return False


def _listing(row: dict[str,str]) -> BusinessListing | None:
    if row.get("hit_type") != "2" or not all(row.get(key) for key in ("name","phone","address","source_url")):
        return None
    return BusinessListing(
        name=row["name"], category="business directory entry", address=row["address"],
        latitude=None, longitude=None, phone=row["phone"], website=None,
        source_url=row["source_url"],
    )


class _HitParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str,str]]=[];self._row:dict[str,str]|None=None
        self._capture_name=False

    def handle_starttag(self,tag:str,attrs:list[tuple[str,str|None]])->None:
        values=dict(attrs);classes=set((values.get("class") or "").split())
        if "entry" in classes and "hitlistitem" in classes:
            self._finish_row();self._row={"hit_type":values.get("data-hittype") or ""}
        if self._row is None:return
        if tag=="a" and "name" in classes:
            href=values.get("href") or ""
            if href.startswith("https://adresse.dastelefonbuch.de/"):self._row["source_url"]=href
        if values.get("itemprop")=="name":self._capture_name=True
        if tag=="a" and "addr" in classes and values.get("title"):self._row["address"]=" ".join((values["title"] or "").split())

    def handle_data(self,data:str)->None:
        if self._row is not None and self._capture_name and data.strip():
            self._row["name"]=(self._row.get("name","")+" "+data.strip()).strip()

    def handle_comment(self,data:str)->None:
        if self._row is None:return
        match=re.match(r"\s*phoneTo:\s*(.*?)\s*$",data,re.I)
        if match:self._row["phone"]=" ".join(match.group(1).split())

    def handle_endtag(self,tag:str)->None:
        if tag=="span" and self._capture_name:self._capture_name=False

    def finish(self)->None:self._finish_row()
    def _finish_row(self)->None:
        if self._row is not None:self.rows.append(self._row)
        self._row=None;self._capture_name=False
