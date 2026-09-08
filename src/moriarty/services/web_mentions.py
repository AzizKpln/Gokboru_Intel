from __future__ import annotations

import phonenumbers
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from threading import Lock
from time import monotonic
from urllib.parse import unquote, urlparse

from moriarty.domain.models import (
    Evidence,
    MentionCategory,
    Source,
    WebMention,
    WebMentionsResult,
)
from moriarty.providers.search_backend import SearchBackend
from moriarty.services.phone_analyzer import PhoneAnalyzer
from moriarty.services.web_page_verifier import verify_web_page

_SOCIAL_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "youtube.com",
}
_FORUM_DOMAINS = {"reddit.com", "quora.com", "eksisozluk.com"}
_BUSINESS_HINTS = (
    "business",
    "company",
    "contact",
    "directory",
    "firma",
    "maps",
    "yellowpages",
)
_DOCUMENT_SUFFIXES = (".csv", ".doc", ".docx", ".pdf", ".txt", ".xls", ".xlsx")
_REPUTATION_HINTS=("who-calls","whocalled","unknownphone","tellows","spam-call","spam_calls","phone-check","number/")
_URL_NUMBER=re.compile(r"(?<!\d)\+?\d[\d()._-]{6,}\d(?!\d)")


class WebMentionsService:
    def __init__(
        self,
        analyzer: PhoneAnalyzer,
        backend: SearchBackend,
        max_results: int = 10,
        verify: bool = False,
        timeout_seconds: float = 30.0,
        loader=None,
        intelligence=None,
        intelligence_limit: int = 3,
    ) -> None:
        if max_results <= 0 or timeout_seconds <= 0 or intelligence_limit <= 0:
            raise ValueError("Web mention limits and timeout must be greater than zero.")
        self._analyzer = analyzer
        self._backend = backend
        self._max_results = max_results
        self._verify=verify or intelligence is not None
        self._timeout=timeout_seconds
        self._loader=loader
        self._intelligence,self._intelligence_limit=intelligence,intelligence_limit

    @property
    def provider_name(self) -> str:
        return f"web_mentions:{self._backend.name}"

    def discover(
        self, raw_number: str, default_region: str | None = None
    ) -> WebMentionsResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        reserve=min(8.0,max(3.0,self._timeout*.15));deadline=monotonic()+max(1.0,self._timeout-reserve)
        queries = _build_queries(phone.e164)
        mentions: list[WebMention] = []
        seen_urls: set[str] = set()
        remaining = self._max_results

        for query in queries:
            if remaining <= 0:
                break
            for result in self._backend.search(query, remaining):
                canonical = _canonical_url(result.url)
                if not canonical or canonical in seen_urls:
                    continue
                seen_urls.add(canonical)
                category, confidence = _classify(result.url, result.title)
                mentions.append(
                    WebMention(
                        title=result.title,
                        url=result.url,
                        domain=urlparse(result.url).netloc.lower().removeprefix("www."),
                        category=category,
                        matched_query=query,
                        confidence=confidence,
                    )
                )
                remaining -= 1
                if remaining <= 0:
                    break
        discovered=len(mentions)
        if not self._verify:return WebMentionsResult(queries=queries,mentions=tuple(mentions),discovered_count=discovered)
        verified=[];rejected=[];slots=[self._intelligence_limit];lock=Lock()
        eligible=[]
        for index,mention in enumerate(mentions):
            if mention.category is MentionCategory.DOCUMENT:rejected.append((index,{"url":mention.url,"reason":"Document result; use the documents module."}))
            elif _url_contains_different_phone(mention.url,phone.e164,phone.region_code,self._analyzer):rejected.append((index,{"url":mention.url,"reason":"URL contains a different valid phone number."}))
            else:eligible.append((index,mention))
        executor=ThreadPoolExecutor(max_workers=min(4,len(eligible) or 1),thread_name_prefix="moriarty-web-verify")
        futures={executor.submit(self._verify_one,mention,phone.e164,phone.region_code,deadline,slots,lock):(index,mention) for index,mention in eligible}
        try:
            for future in as_completed(futures,timeout=max(.05,deadline-monotonic())):
                index,mention=futures[future]
                try:verified.append((index,future.result()))
                except Exception as exc:rejected.append((index,{"url":mention.url,"reason":str(exc) or type(exc).__name__}))
        except TimeoutError:pass
        finally:
            for future,(index,mention) in futures.items():
                if not future.done():future.cancel();rejected.append((index,{"url":mention.url,"reason":"Page verification time budget exhausted."}))
            executor.shutdown(wait=False,cancel_futures=True)
        return WebMentionsResult(queries,tuple(item for _,item in sorted(verified)),discovered,tuple(item for _,item in sorted(rejected)))

    def _verify_one(self,mention:WebMention,expected:str,region:str|None,deadline:float,slots:list[int],lock:Lock)->WebMention:
        remaining=deadline-monotonic()
        if remaining<=0:raise TimeoutError("Page verification time budget exhausted.")
        verification=verify_web_page(mention.url,expected,region,self._analyzer,min(15.0,remaining),loader=self._loader)
        final_url=str(verification["final_url"]);updated=replace(mention,url=final_url,domain=urlparse(final_url).netloc.lower().removeprefix("www."),verification=verification)
        if self._intelligence is None:return updated
        with lock:
            if slots[0]<=0:return updated
            slots[0]-=1
        remaining=deadline-monotonic()
        if remaining<=1:return replace(updated,intelligence={"status":"skipped","reason":"Provider time budget exhausted."})
        try:data=self._intelligence.analyze(str(verification["visible_context"]),expected,mention.title,min(30.0,remaining))
        except Exception as exc:return replace(updated,intelligence={"status":"error","error":str(exc) or type(exc).__name__})
        return replace(updated,intelligence=_sanitize_intelligence(data,str(verification["visible_context"]),expected,region,self._analyzer))

    def evidence_for(self, result: WebMentionsResult) -> tuple[Evidence, ...]:
        return tuple(
            Evidence(
                kind=f"web_mention.{mention.category}",
                value=mention.url,
                source=Source(provider=self.provider_name, url=mention.url),
                confidence=mention.confidence,
                attributes={"title": mention.title, "domain": mention.domain,"verification":mention.verification,"intelligence":mention.intelligence},
            )
            for mention in result.mentions
        )


def _build_queries(e164: str) -> tuple[str, ...]:
    number = phonenumbers.parse(e164, None)
    digits = e164.removeprefix("+")
    international = phonenumbers.format_number(
        number, phonenumbers.PhoneNumberFormat.INTERNATIONAL
    )
    national = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
    compact_national = "".join(character for character in national if character.isdigit())
    country_code = f"+{number.country_code}"

    
    
    candidates = (
        e164,
        digits,
        international,
        national,
        f"{country_code} {compact_national}",
    )
    return tuple(dict.fromkeys(f'"{candidate}"' for candidate in candidates))


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _classify(url: str, title: str) -> tuple[MentionCategory, float]:
    parsed = urlparse(url)
    domain = parsed.netloc.lower().removeprefix("www.")
    text = f"{domain} {parsed.path} {title}".lower()
    if any(domain == item or domain.endswith(f".{item}") for item in _SOCIAL_DOMAINS):
        return MentionCategory.SOCIAL_PROFILE, 0.85
    if any(domain == item or domain.endswith(f".{item}") for item in _FORUM_DOMAINS):
        return MentionCategory.FORUM, 0.85
    if parsed.path.lower().endswith(_DOCUMENT_SUFFIXES):
        return MentionCategory.DOCUMENT, 0.9
    if any(hint in text for hint in _REPUTATION_HINTS):
        return MentionCategory.PHONE_REPUTATION, 0.85
    if any(hint in text for hint in _BUSINESS_HINTS):
        return MentionCategory.BUSINESS_LISTING, 0.7
    return MentionCategory.OTHER, 0.5


def _url_contains_different_phone(url:str,expected:str,region:str|None,analyzer:PhoneAnalyzer)->bool:
    candidates=[]
    for raw in _URL_NUMBER.findall(unquote(urlparse(url).path)):
        cleaned=raw.replace("_"," ")
        try:analysis=analyzer.analyze(cleaned,region)
        except Exception:continue
        if analysis.is_possible:candidates.append(analysis.e164)
    return bool(candidates) and expected not in candidates


def _sanitize_intelligence(data:dict,context:str,expected:str,region:str|None,analyzer:PhoneAnalyzer)->dict:
    folded=context.casefold()
    def visible(value)->str:
        clean=str(value or "").strip()
        return clean if clean.casefold() in folded else ""
    additional=[]
    for item in data.get("additional_phones") or ():
        raw=visible(item.get("raw") or "")
        if not raw:continue
        try:e164=analyzer.analyze(raw,region).e164
        except Exception:continue
        if e164!=expected:additional.append({"raw":raw,"e164":e164,"role":str(item.get("role") or "")})
    try:confidence=max(0.0,min(1.0,float(data.get("confidence") or 0.0)))
    except (TypeError,ValueError):confidence=0.0
    return {
        "status":"success","page_type":str(data.get("page_type") or ""),"language":str(data.get("language") or ""),
        "organization":visible(data.get("organization")),"department":visible(data.get("department")),
        "queried_phone_role":str(data.get("queried_phone_role") or ""),"business_category":str(data.get("business_category") or ""),
        "address":visible(data.get("address")),"emails":tuple(value for item in (data.get("emails") or ()) if (value:=visible(item))),
        "additional_phones":tuple(additional),"websites":tuple(value for item in (data.get("websites") or ()) if (value:=visible(item))),
        "visible_context":context,"confidence":confidence,
    }
