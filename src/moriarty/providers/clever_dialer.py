from __future__ import annotations
import html, re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import phonenumbers
from moriarty.domain.models import LookupStatus, ReputationResult
from moriarty.providers.whocalled_uk import PageResponse, ReputationSourceError
from moriarty.services.phone_analyzer import PhoneAnalyzer

class CleverDialerClient:
    name = "clever_dialer"
    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 8.0, loader=None) -> None:
        if timeout_seconds <= 0: raise ValueError("Source timeout must be greater than zero.")
        self._analyzer, self._timeout_seconds, self._loader = analyzer, timeout_seconds, loader or _load_page
    def lookup(self, raw_number: str, default_region: str | None = None) -> ReputationResult:
        phone = self._analyzer.analyze(raw_number, default_region)
        if phone.region_code == "GB":
            parsed=phonenumbers.parse(phone.e164,None); national=phonenumbers.format_number(parsed,phonenumbers.PhoneNumberFormat.NATIONAL); digits="".join(c for c in national if c.isdigit()); host="www.cleverdialer.co.uk"
        elif phone.country_code == 1:
            digits=phone.e164.removeprefix("+")[1:]; host="www.cleverdialer.com"
        else: return ReputationResult(self.name,LookupStatus.NOT_APPLICABLE,phone.e164,None)
        url=f"https://{host}/phonenumber/{digits}"; response=self._loader(url,self._timeout_seconds)
        if response.status==404: return ReputationResult(self.name,LookupStatus.NOT_FOUND,phone.e164,url)
        if response.status!=200: raise ReputationSourceError(f"CleverDialer returned HTTP {response.status}.")
        return _parse_page(response.body,phone.e164,url)

def _load_page(url:str,timeout:float)->PageResponse:
    request=Request(url,headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    try:
        with urlopen(request,timeout=timeout) as response:return PageResponse(response.status,response.read().decode(response.headers.get_content_charset() or "utf-8",errors="replace"))
    except HTTPError as exc:
        if exc.code==404:return PageResponse(404,"")
        raise ReputationSourceError(f"CleverDialer returned HTTP {exc.code}.") from exc
    except URLError as exc:raise ReputationSourceError(f"CleverDialer network error: {exc.reason}") from exc

def _parse_page(body:str,e164:str,url:str)->ReputationResult:
    rating=re.search(r'<div class="rating-text">.*?<span>([\d.]+) out of 5 stars</span>.*?<span[^>]*>\s*&bull;\s*(One|[\d,]+) ratings?</span>',body,re.I|re.S)
    if not rating or float(rating.group(1))==0:return ReputationResult(CleverDialerClient.name,LookupStatus.NOT_FOUND,e164,url)
    score=float(rating.group(1)); count=1 if rating.group(2).lower()=="one" else int(rating.group(2).replace(",",""))
    spam_page = re.search(
        r'<main\s+class=["\'][^"\']*\bsite-phone-number-spam\b[^"\']*["\']',
        body,
        re.I,
    )
    level="Warning" if spam_page or score<=2 else ("Positive" if score>=4 else "Neutral")
    summary=re.search(r'<section class="summary-of-comments"[^>]*>\s*<p>(.*?)</p>',body,re.I|re.S)
    blocked=re.search(r"([\d,]+) times blocked by users",body,re.I)
    categories={"Blocked by users":int(blocked.group(1).replace(",",""))} if blocked else None
    comments=(_clean(summary.group(1)),) if summary and _clean(summary.group(1)) else None
    return ReputationResult(source=CleverDialerClient.name,status=LookupStatus.FOUND,number=e164,url=url,security_level=level,report_count=count,categories=categories,comments=comments)

def _clean(value:str)->str:return " ".join(html.unescape(re.sub(r"<[^>]+>","",value)).split())
