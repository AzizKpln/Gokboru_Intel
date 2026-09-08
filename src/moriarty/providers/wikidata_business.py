from __future__ import annotations
import json,re
from time import sleep
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
import phonenumbers
from moriarty.domain.models import BusinessListing,BusinessListingsResult
from moriarty.services.phone_analyzer import PhoneAnalyzer

class WikidataBusinessClient:
 name="wikidata"
 def __init__(self,analyzer:PhoneAnalyzer,timeout_seconds:float=15.0,loader=None,max_results:int=20)->None:
  if timeout_seconds<=0:raise ValueError("Source timeout must be greater than zero.")
  if max_results<=0:raise ValueError("Maximum results must be greater than zero.")
  self._analyzer,self._timeout_seconds,self._loader,self._max_results=analyzer,timeout_seconds,loader or _load,max_results
 def lookup(self,raw_number:str,default_region:str|None=None)->BusinessListingsResult:
  phone=self._analyzer.analyze(raw_number,default_region);payload=self._loader(_query(_variants(phone.e164),self._max_results),self._timeout_seconds)
  bindings=payload.get("results",{}).get("bindings",[]);listings=tuple(_listing(x) for x in bindings if isinstance(x,dict))
  return BusinessListingsResult(self.name,phone.e164,listings)

def _load(query:str,timeout:float)->dict:
 url="https://query.wikidata.org/sparql?"+urlencode({"query":query,"format":"json"});request=Request(url,headers={"User-Agent":"Moriarty-V5/0.1 (+public business lookup)","Accept":"application/sparql-results+json"})
 for attempt in range(2):
  try:
   with urlopen(request,timeout=max(1.0,timeout-(2.0*attempt))) as response:return json.loads(response.read().decode("utf-8",errors="replace"))
  except HTTPError as exc:
   if attempt==0 and exc.code in {429,500,502,503,504}:
    retry_after=exc.headers.get("Retry-After") if exc.headers else None
    try:delay=min(2.0,max(0.25,float(retry_after)))
    except (TypeError,ValueError):delay=1.0
    sleep(delay);continue
   raise RuntimeError(f"Wikidata Query Service returned HTTP {exc.code}.") from exc
  except URLError as exc:raise RuntimeError(f"Wikidata Query Service network error: {exc.reason}") from exc
  except json.JSONDecodeError as exc:raise RuntimeError("Wikidata Query Service returned invalid JSON.") from exc
 raise RuntimeError("Wikidata Query Service unavailable after retry.")

def _variants(e164:str)->tuple[str,...]:
 number=phonenumbers.parse(e164,None);values=(e164,e164.removeprefix("+"),phonenumbers.format_number(number,phonenumbers.PhoneNumberFormat.INTERNATIONAL),phonenumbers.format_number(number,phonenumbers.PhoneNumberFormat.NATIONAL),phonenumbers.format_number(number,phonenumbers.PhoneNumberFormat.RFC3966).removeprefix("tel:"))
 return tuple(dict.fromkeys(values))

def _query(variants:tuple[str,...],limit:int)->str:
 values=" ".join(json.dumps(value) for value in variants)
 return f'''SELECT ?item ?itemLabel ?phone ?website ?coord ?typeLabel WHERE {{ VALUES ?phone {{ {values} }} ?item wdt:P1329 ?phone. OPTIONAL {{?item wdt:P856 ?website}} OPTIONAL {{?item wdt:P625 ?coord}} OPTIONAL {{?item wdt:P31 ?type}} SERVICE wikibase:label {{bd:serviceParam wikibase:language "en,tr".}} }} LIMIT {limit}'''

def _listing(row:dict)->BusinessListing:
 def value(key):return (row.get(key) or {}).get("value")
 item=value("item") or "";lat=lon=None;coord=value("coord")
 if coord:
  match=re.match(r"Point\(([-\d.]+) ([-\d.]+)\)",coord)
  if match:lon,lat=float(match.group(1)),float(match.group(2))
 return BusinessListing(name=value("itemLabel") or item.rsplit("/",1)[-1] or "Unnamed entity",category=value("typeLabel"),address=None,latitude=lat,longitude=lon,phone=value("phone") or "",website=value("website"),source_url=item.replace("http://","https://"))
