from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

from moriarty.domain.models import DisposableNumberResult
from moriarty.services.phone_analyzer import PhoneAnalyzer

_SOURCES=(("receivesms.co","https://www.receivesms.co/"),("receive-smss.com","https://receive-smss.com/"),("sms-online.co","https://sms-online.co/receive-free-sms"),("receive-sms-online.info","https://receive-sms-online.info/"),("sms24.me","https://sms24.me/"))

class DisposableNumberService:
    def __init__(self,analyzer:PhoneAnalyzer,backend=None,max_results:int=10,timeout_seconds:float=12.0,loader=None,sources=None)->None:
        if max_results<=0 or timeout_seconds<=0:raise ValueError("Disposable limits and timeout must be greater than zero.")
        self._analyzer,self._limit,self._timeout=analyzer,max_results,timeout_seconds;self._loader=loader or _load;self._sources=tuple(sources or _SOURCES)
    def check(self,raw_number:str,default_region:str|None=None)->DisposableNumberResult:
        phone=self._analyzer.analyze(raw_number,default_region);expected=phone.e164.removeprefix("+");matches=[];checked=[];failures=[]
        executor=ThreadPoolExecutor(max_workers=min(5,len(self._sources) or 1),thread_name_prefix="moriarty-public-sms")
        futures={executor.submit(self._loader,url,self._timeout):(name,url) for name,url in self._sources}
        try:
            for future in as_completed(futures):
                name,url=futures[future]
                try:body=future.result();checked.append(name)
                except Exception as exc:failures.append({"source":name,"url":url,"error":str(exc) or type(exc).__name__});continue
                if expected in re.sub(r"\D","",body):matches.append({"title":f"Public SMS directory: {name}","url":url,"domain":name})
        finally:executor.shutdown(wait=False,cancel_futures=True)
        classification="possible_public_sms_number" if matches else "not_observed_on_checked_directory_pages" if checked else "inconclusive_sources_unavailable"
        return DisposableNumberResult(phone.e164,classification,tuple(matches[:self._limit]),(),checked_sources=tuple(sorted(checked)),failures=tuple(failures))

def _load(url:str,timeout:float)->str:
    request=Request(url,headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36","Accept":"text/html,application/xhtml+xml","Accept-Language":"en-US,en;q=0.8"})
    try:
        with urlopen(request,timeout=timeout) as response:return response.read(3_000_001).decode(response.headers.get_content_charset() or "utf-8",errors="replace")
    except HTTPError as exc:raise RuntimeError(f"HTTP {exc.code}") from exc
    except URLError as exc:raise RuntimeError(f"Network error: {exc.reason}") from exc
