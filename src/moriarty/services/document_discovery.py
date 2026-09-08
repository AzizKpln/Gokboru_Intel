from __future__ import annotations

import ipaddress
import re
import socket
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from io import BytesIO
from pathlib import PurePosixPath
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

import phonenumbers

from moriarty.domain.models import DocumentDiscoveryResult, DocumentFinding
from moriarty.providers.search_backend import SearchBackend
from moriarty.services.phone_analyzer import PhoneAnalyzer

_PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s()./-]{5,}\d(?!\w)")
_SUPPORTED = {".pdf":"pdf", ".docx":"docx", ".xlsx":"xlsx"}


class DocumentDiscoveryService:
    def __init__(self, analyzer:PhoneAnalyzer, backend:SearchBackend, timeout_seconds:float=30.0, max_results:int=10, max_bytes:int=10_000_000, loader=None, ocr=None, ocr_limit:int=3, intelligence=None, intelligence_limit:int=3)->None:
        if timeout_seconds<=0 or max_results<=0 or max_bytes<=0 or ocr_limit<=0 or intelligence_limit<=0: raise ValueError("Document limits and timeout must be greater than zero.")
        self._analyzer,self._backend=analyzer,backend
        self._timeout,self._max_results,self._max_bytes=timeout_seconds,max_results,max_bytes
        self._loader=loader or _load_document
        self._ocr,self._ocr_limit=ocr,ocr_limit
        self._intelligence,self._intelligence_limit=intelligence,intelligence_limit

    @property
    def provider_name(self)->str:return f"public_documents:{self._backend.name}"

    def discover(self,raw_number:str,default_region:str|None=None)->DocumentDiscoveryResult:
        phone=self._analyzer.analyze(raw_number,default_region);queries=_queries(phone.e164)
        
        reserve=min(8.0,max(3.0,self._timeout*.15))
        deadline=monotonic()+max(1.0,self._timeout-reserve)
        candidates=[];seen=set()
        for query in queries:
            if monotonic()>=deadline:break
            for result in self._backend.search(query,self._max_results):
                clean=result.url.split("#",1)[0]
                if clean not in seen:seen.add(clean);candidates.append(result)
                if len(candidates)>=self._max_results:break
            if len(candidates)>=self._max_results:break
        findings=[];failures=[];ocr_slots=[self._ocr_limit];ocr_lock=Lock();intelligence_slots=[self._intelligence_limit];intelligence_lock=Lock()
        executor=ThreadPoolExecutor(max_workers=min(4,len(candidates) or 1),thread_name_prefix="moriarty-document")
        futures={executor.submit(self._inspect,result,phone.e164,phone.region_code,deadline,ocr_slots,ocr_lock,intelligence_slots,intelligence_lock):result for result in candidates}
        try:
            remaining=max(0.05,deadline-monotonic())
            for future in as_completed(futures,timeout=remaining):
                result=futures[future]
                try:
                    finding=future.result()
                    if finding:findings.append(finding)
                except Exception as exc:failures.append({"url":result.url,"error":str(exc) or type(exc).__name__})
        except TimeoutError:
            pass
        finally:
            for future,result in futures.items():
                if not future.done():
                    future.cancel();failures.append({"url":result.url,"error":"Document skipped because the provider time budget was exhausted."})
            executor.shutdown(wait=False,cancel_futures=True)
        return DocumentDiscoveryResult(phone.e164,queries,len(candidates),tuple(findings),tuple(failures))

    def _inspect(self,result,expected:str,region:str|None,deadline:float,ocr_slots:list[int],ocr_lock:Lock,intelligence_slots:list[int],intelligence_lock:Lock)->DocumentFinding|None:
        remaining=deadline-monotonic()
        if remaining<=0:raise TimeoutError("Document skipped because the provider time budget was exhausted.")
        final_url,payload,content_type=self._loader(result.url,min(15.0,remaining),self._max_bytes)
        doc_type=_document_type(final_url,content_type,payload)
        text=_extract_text(doc_type,payload)
        match=_find_phone(text,expected,region,self._analyzer)
        if match:
            finding=DocumentFinding(result.title,final_url,doc_type,match,_context(text,match),.95)
            return self._enrich(finding,expected,region,deadline,intelligence_slots,intelligence_lock)
        if doc_type=="pdf" and self._ocr is not None and len(text.strip())<20:
            with ocr_lock:
                if ocr_slots[0]<=0:return None
                ocr_slots[0]-=1
            remaining=deadline-monotonic()
            if remaining<=1:raise TimeoutError("OCR skipped because the provider time budget was exhausted.")
            data=self._ocr.analyze(payload,expected,min(30.0,remaining))
            candidate=" ".join((str(data.get("matched_text") or ""),str(data.get("context") or "")))
            verified=_find_phone(candidate,expected,region,self._analyzer)
            if data.get("matched") is True and verified:
                entities={key:str(data.get(key) or "") for key in ("organization","department","address","email") if data.get(key)}
                page=int(data.get("page") or 0) or None
                finding=DocumentFinding(result.title,final_url,doc_type,str(data.get("matched_text") or verified),str(data.get("context") or verified),.90,page,"gemini_ocr",entities or None)
                return self._enrich(finding,expected,region,deadline,intelligence_slots,intelligence_lock)
        return None

    def _enrich(self,finding:DocumentFinding,expected:str,region:str|None,deadline:float,slots:list[int],lock:Lock)->DocumentFinding:
        if self._intelligence is None:return finding
        with lock:
            if slots[0]<=0:return finding
            slots[0]-=1
        remaining=deadline-monotonic()
        if remaining<=1:return replace(finding,intelligence={"status":"skipped","reason":"Provider time budget exhausted."})
        try:data=self._intelligence.analyze(finding.context,expected,finding.title,min(30.0,remaining))
        except Exception as exc:return replace(finding,intelligence={"status":"error","error":str(exc) or type(exc).__name__})
        context=finding.context;folded=context.casefold()
        visible=lambda value: str(value).strip() if str(value).strip().casefold() in folded else ""
        additional=[]
        for item in data.get("additional_phones") or ():
            raw=visible(item.get("raw") or "")
            if not raw:continue
            try:e164=self._analyzer.analyze(raw,region).e164
            except Exception:continue
            if e164!=expected:additional.append({"raw":raw,"e164":e164,"role":str(item.get("role") or "")})
        confidence=max(0.0,min(1.0,float(data.get("confidence") or 0.0)))
        intelligence={
            "status":"success","document_category":str(data.get("document_category") or ""),"language":str(data.get("language") or ""),
            "organization":visible(data.get("organization") or ""),"department":visible(data.get("department") or ""),
            "queried_phone_role":str(data.get("queried_phone_role") or ""),"address":visible(data.get("address") or ""),
            "emails":tuple(value for item in (data.get("emails") or ()) if (value:=visible(item))),
            "additional_phones":tuple(additional),"websites":tuple(value for item in (data.get("websites") or ()) if (value:=visible(item))),
            "visible_context":context,"confidence":confidence,
        }
        method="gemini_ocr_and_intelligence" if finding.extraction_method=="gemini_ocr" else "local_text_plus_gemini"
        return replace(finding,extraction_method=method,intelligence=intelligence)


def _queries(e164:str)->tuple[str,...]:
    number=phonenumbers.parse(e164,None)
    values=(e164,phonenumbers.format_number(number,phonenumbers.PhoneNumberFormat.INTERNATIONAL),phonenumbers.format_number(number,phonenumbers.PhoneNumberFormat.NATIONAL))
    return tuple(dict.fromkeys(f'"{value}" (filetype:pdf OR filetype:docx OR filetype:xlsx)' for value in values))


def _suffix_type(url:str)->str|None:return _SUPPORTED.get(PurePosixPath(urlsplit(url).path.lower()).suffix)


def _document_type(url:str,content_type:str,payload:bytes)->str:
    suffix=_suffix_type(url)
    if payload.startswith(b"%PDF-"):return "pdf"
    if payload.startswith(b"PK"):
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:names=set(archive.namelist())
            if "word/document.xml" in names:return "docx"
            if "xl/workbook.xml" in names:return "xlsx"
        except zipfile.BadZipFile:pass
    media=content_type.split(";",1)[0].strip().lower()
    mapped={"application/pdf":"pdf","application/vnd.openxmlformats-officedocument.wordprocessingml.document":"docx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":"xlsx"}.get(media)
    if mapped:return mapped
    raise RuntimeError("Downloaded file is not a supported PDF, DOCX, or XLSX document.")


def _extract_text(doc_type:str,payload:bytes)->str:
    if doc_type=="pdf":return _extract_pdf(payload)
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names=archive.namelist()
        wanted=[name for name in names if (doc_type=="docx" and name.startswith("word/") and name.endswith(".xml")) or (doc_type=="xlsx" and (name=="xl/sharedStrings.xml" or name.startswith("xl/worksheets/") and name.endswith(".xml")))]
        return "\n".join(_xml_text(archive.read(name)) for name in wanted)


def _extract_pdf(payload:bytes)->str:
    try:from pypdf import PdfReader
    except ImportError as exc:raise RuntimeError("PDF support is unavailable; reinstall Moriarty dependencies.") from exc
    try:return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(payload)).pages)
    except Exception as exc:raise RuntimeError("PDF text extraction failed.") from exc


def _xml_text(payload:bytes)->str:
    try:return " ".join(text.strip() for text in ElementTree.fromstring(payload).itertext() if text.strip())
    except ElementTree.ParseError as exc:raise RuntimeError("Office document contains invalid XML.") from exc


def _find_phone(text:str,expected:str,region:str|None,analyzer:PhoneAnalyzer)->str|None:
    for candidate in _PHONE_PATTERN.findall(text):
        try:
            if analyzer.analyze(candidate.strip(),region).e164==expected:return candidate.strip()
        except Exception:continue
    return None


def _context(text:str,matched:str,radius:int=250)->str:
    compact=" ".join(text.split());position=compact.find(" ".join(matched.split()))
    if position<0:return matched
    return compact[max(0,position-radius):position+len(matched)+radius]


def _load_document(url:str,timeout:float,max_bytes:int)->tuple[str,bytes,str]:
    _validate_public_url(url);opener=build_opener(_PublicRedirect())
    request=Request(url,headers={"User-Agent":"Moriarty-V5/0.1 (+public document verification)","Accept":"application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
    with opener.open(request,timeout=timeout) as response:
        length=response.headers.get("Content-Length")
        if length and int(length)>max_bytes:raise RuntimeError("Document exceeds the configured size limit.")
        payload=response.read(max_bytes+1)
        if len(payload)>max_bytes:raise RuntimeError("Document exceeds the configured size limit.")
        return response.geturl(),payload,response.headers.get("Content-Type") or ""


def _validate_public_url(url:str)->None:
    parts=urlsplit(url)
    if parts.scheme not in {"http","https"} or not parts.hostname or parts.username or parts.password:raise ValueError("Unsafe document URL.")
    try:addresses={item[4][0] for item in socket.getaddrinfo(parts.hostname,None)}
    except socket.gaierror as exc:raise ValueError("Document hostname could not be resolved.") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):raise ValueError("Document URL resolves to a non-public address.")


class _PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        _validate_public_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)
