from __future__ import annotations
import html,json,re
from urllib.error import HTTPError,URLError
from urllib.parse import quote
from urllib.request import Request,urlopen
from moriarty.domain.models import LookupStatus,ReputationResult
from moriarty.providers.whocalled_uk import PageResponse,ReputationSourceError
from moriarty.services.phone_analyzer import PhoneAnalyzer

class WhoCalledTodayClient:
 name="who_called_today"
 def __init__(self,analyzer:PhoneAnalyzer,timeout_seconds:float=8.0,loader=None)->None:
  if timeout_seconds<=0:raise ValueError("Source timeout must be greater than zero.")
  self._analyzer,self._timeout_seconds,self._loader=analyzer,timeout_seconds,loader or _load_page
 def lookup(self,raw_number:str,default_region:str|None=None)->ReputationResult:
  phone=self._analyzer.analyze(raw_number,default_region);url=f"https://whocalled.today/phonenumber/{quote(phone.e164,safe='')}";response=self._loader(url,self._timeout_seconds)
  if response.status==404:return ReputationResult(self.name,LookupStatus.NOT_FOUND,phone.e164,url)
  if response.status!=200:raise ReputationSourceError(f"WhoCalled.Today returned HTTP {response.status}.")
  return _parse_page(response.body,phone.e164,url)

def _load_page(url:str,timeout:float)->PageResponse:
 request=Request(url,headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
 try:
  with urlopen(request,timeout=timeout) as response:return PageResponse(response.status,response.read().decode(response.headers.get_content_charset() or "utf-8",errors="replace"))
 except HTTPError as exc:
  if exc.code==404:return PageResponse(404,"")
  raise ReputationSourceError(f"WhoCalled.Today returned HTTP {exc.code}.") from exc
 except URLError as exc:raise ReputationSourceError(f"WhoCalled.Today network error: {exc.reason}") from exc

def _parse_page(body:str,e164:str,url:str)->ReputationResult:
 thing=None
 match=re.search(r'<script\s+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',body,re.I|re.S)
 if match:
  try:
   data=json.loads(html.unescape(match.group(1)));thing=next((x for x in data.get("@graph",[]) if x.get("@type")=="Thing"),None)
  except (json.JSONDecodeError,TypeError,AttributeError):pass
 if not thing:return ReputationResult(WhoCalledTodayClient.name,LookupStatus.NOT_FOUND,e164,url)
 props={item.get("name"):item.get("value") for item in thing.get("additionalProperty",[]) if isinstance(item,dict)}
 reports=int(props.get("Reports") or 0)
 if reports<=0:return ReputationResult(WhoCalledTodayClient.name,LookupStatus.NOT_FOUND,e164,url)
 conclusion=str(props.get("Conclusion") or "Reported");lookups=int(props.get("Lookups") or 0) or None
 categories={"Approved comments":int(props.get("Approved comments") or 0)}
 return ReputationResult(source=WhoCalledTodayClient.name,status=LookupStatus.FOUND,number=e164,url=url,security_level=conclusion,report_count=reports,lookup_count=lookups,categories=categories)
