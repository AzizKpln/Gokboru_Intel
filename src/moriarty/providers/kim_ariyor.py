from __future__ import annotations
import html,json,re
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
import phonenumbers
from moriarty.domain.models import LookupStatus,ReputationResult
from moriarty.providers.whocalled_uk import PageResponse,ReputationSourceError
from moriarty.services.phone_analyzer import PhoneAnalyzer

class KimAriyorClient:
 name="kim_ariyor"
 def __init__(self,analyzer:PhoneAnalyzer,timeout_seconds:float=8.0,loader=None,max_comments:int=10)->None:
  if timeout_seconds<=0:raise ValueError("Source timeout must be greater than zero.")
  if max_comments<0:raise ValueError("Maximum comments cannot be negative.")
  self._analyzer,self._timeout_seconds,self._loader,self._max_comments=analyzer,timeout_seconds,loader or _load_page,max_comments
 def lookup(self,raw_number:str,default_region:str|None=None)->ReputationResult:
  phone=self._analyzer.analyze(raw_number,default_region)
  if phone.region_code!="TR":return ReputationResult(self.name,LookupStatus.NOT_APPLICABLE,phone.e164,None)
  parsed=phonenumbers.parse(phone.e164,None);national=phonenumbers.format_number(parsed,phonenumbers.PhoneNumberFormat.NATIONAL);digits="".join(c for c in national if c.isdigit());url=f"https://www.kimariyor.com.tr/number/{digits}";response=self._loader(url,self._timeout_seconds)
  if response.status==404:return ReputationResult(self.name,LookupStatus.NOT_FOUND,phone.e164,url)
  if response.status!=200:raise ReputationSourceError(f"Kim Arıyor returned HTTP {response.status}.")
  return _parse_page(response.body,phone.e164,url,self._max_comments)

def _load_page(url:str,timeout:float)->PageResponse:
 request=Request(url,headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8","Accept-Language":"tr-TR,tr;q=0.9"})
 try:
  with urlopen(request,timeout=timeout) as response:return PageResponse(response.status,response.read().decode(response.headers.get_content_charset() or "utf-8",errors="replace"))
 except HTTPError as exc:
  if exc.code==404:return PageResponse(404,"")
  raise ReputationSourceError(f"Kim Arıyor returned HTTP {exc.code}.") from exc
 except URLError as exc:raise ReputationSourceError(f"Kim Arıyor network error: {exc.reason}") from exc

def _parse_page(body:str,e164:str,url:str,max_comments:int)->ReputationResult:
 rating=None
 for raw in re.findall(r'<script\s+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',body,re.I|re.S):
  try:data=json.loads(html.unescape(raw))
  except (json.JSONDecodeError,TypeError):continue
  if isinstance(data,dict) and data.get("@type")=="Product":rating=data.get("aggregateRating");break
 if not isinstance(rating,dict):return ReputationResult(KimAriyorClient.name,LookupStatus.NOT_FOUND,e164,url)
 count=int(rating.get("reviewCount") or 0);score=float(rating.get("ratingValue") or 0)
 if count<=0:return ReputationResult(KimAriyorClient.name,LookupStatus.NOT_FOUND,e164,url)
 risk=re.search(r"%(\d+) risk oranı",body,re.I);lookups=re.search(r"toplam\s+([\d.]+)\s+kez sorgulama",body,re.I)
 comments=tuple(_clean(x) for x in re.findall(r'<p\s+class=["\'][^"\']*\bcomment-text\b[^"\']*["\'][^>]*>(.*?)</p>',body,re.I|re.S)[:max_comments] if _clean(x))
 level="Dangerous" if score<=2 else ("Safe" if score>=4 else "Neutral")
 categories={"Risk percent":int(risk.group(1))} if risk else None
 return ReputationResult(source=KimAriyorClient.name,status=LookupStatus.FOUND,number=e164,url=url,security_level=level,report_count=count,lookup_count=int(lookups.group(1).replace(".","")) if lookups else None,categories=categories,comments=comments or None)

def _clean(value:str)->str:return " ".join(html.unescape(re.sub(r"<[^>]+>","",value)).split())
