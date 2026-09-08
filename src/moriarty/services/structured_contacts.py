from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from moriarty.domain.models import StructuredContactsResult
from moriarty.services.phone_analyzer import PhoneAnalyzer

_PHONE=re.compile(r"(?<!\w)\+?\d[\d\s()./-]{5,}\d(?!\w)")
_EMAIL=re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",re.I)


class _Parser(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.links=[];self.jsonld=[];self._json_depth=0;self._parts=[]
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=="a" and values.get("href"):self.links.append(values["href"])
        if tag=="script" and values.get("type","").lower()=="application/ld+json":self._json_depth=1
    def handle_endtag(self,tag):
        if tag=="script" and self._json_depth:
            self.jsonld.append("".join(self._parts));self._parts=[];self._json_depth=0
    def handle_data(self,data):
        if self._json_depth:self._parts.append(data)


def extract_structured_contacts(body:str,source_url:str,analyzer:PhoneAnalyzer,default_region:str|None=None)->StructuredContactsResult:
    parser=_Parser();parser.feed(body)
    raw_phones=[];emails=set(_EMAIL.findall(html.unescape(body)));websites=set();organizations=set();addresses=set();hours=set();sources=set()
    for link in parser.links:
        lowered=link.lower()
        if lowered.startswith("tel:"):raw_phones.append(link[4:]);sources.add("tel_link")
        elif lowered.startswith("mailto:"):emails.add(link[7:].split("?",1)[0]);sources.add("mailto_link")
        elif lowered.startswith(("http://","https://")):websites.add(urljoin(source_url,link))
    for block in parser.jsonld:
        try:data=json.loads(block)
        except json.JSONDecodeError:continue
        for item in _walk(data):
            if not isinstance(item,dict):continue
            sources.add("json_ld")
            if item.get("name"):organizations.add(str(item["name"]))
            for value in _values(item.get("telephone")):raw_phones.append(value)
            for value in _values(item.get("email")):emails.add(value.removeprefix("mailto:"))
            for value in _values(item.get("url")):websites.add(urljoin(source_url,value))
            for value in _values(item.get("openingHours")):hours.add(value)
            address=item.get("address")
            if isinstance(address,str):addresses.add(address)
            elif isinstance(address,dict):
                rendered=", ".join(str(address.get(key)) for key in ("streetAddress","postalCode","addressLocality","addressCountry") if address.get(key))
                if rendered:addresses.add(rendered)
    phones=[];seen=set()
    for raw in raw_phones:
        for candidate in _PHONE.findall(str(raw)) or (str(raw),):
            try:analysis=analyzer.analyze(candidate,default_region)
            except Exception:continue
            if analysis.e164 not in seen:seen.add(analysis.e164);phones.append({"raw":candidate,"e164":analysis.e164,"is_valid":analysis.is_valid})
    return StructuredContactsResult(source_url,tuple(phones),tuple(sorted(emails)),tuple(sorted(websites)),tuple(sorted(organizations)),tuple(sorted(addresses)),tuple(sorted(hours)),tuple(sorted(sources)))


def _walk(value):
    if isinstance(value,list):
        for item in value:yield from _walk(item)
    elif isinstance(value,dict):
        if "@graph" in value:yield from _walk(value["@graph"])
        else:yield value


def _values(value)->tuple[str,...]:
    if value is None:return ()
    if isinstance(value,list):return tuple(str(item) for item in value)
    return (str(value),)
