from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from moriarty.services.phone_analyzer import PhoneAnalyzer

_PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s()./-]{5,}\d(?!\w)")


def verify_web_page(url: str, expected: str, region: str | None, analyzer: PhoneAnalyzer, timeout: float, max_bytes: int = 2_000_000, loader=None) -> dict:
    final_url, html, content_type = (loader or _load_html)(url, timeout, max_bytes)
    if "html" not in content_type.lower() and not html.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise RuntimeError("Downloaded resource is not an HTML page.")
    charset = _charset(content_type)
    text = _visible_text(html.decode(charset, errors="replace"))
    for candidate in _PHONE_PATTERN.findall(text):
        try:
            if analyzer.analyze(candidate.strip(), region).e164 == expected:
                matched = candidate.strip()
                return {"status":"verified","final_url":final_url,"queried_number":expected,"matched_text":matched,"match_type":"exact_normalized","visible_context":_context(text,matched)}
        except Exception:
            continue
    raise RuntimeError("Queried phone number was not found in visible page content.")


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag.lower() in {"script","style","noscript","svg","template"}:self.hidden+=1
    def handle_endtag(self,tag):
        if tag.lower() in {"script","style","noscript","svg","template"} and self.hidden:self.hidden-=1
    def handle_data(self,data):
        if not self.hidden and data.strip():self.parts.append(data.strip())


def _visible_text(html: str) -> str:
    parser=_TextParser();parser.feed(html);return " ".join(" ".join(parser.parts).split())


def _context(text: str, matched: str, radius: int = 350) -> str:
    position=text.find(matched)
    return text[max(0,position-radius):position+len(matched)+radius] if position>=0 else matched


def _charset(content_type: str) -> str:
    match=re.search(r"charset=([^;\s]+)",content_type,re.I)
    return match.group(1).strip('"\'') if match else "utf-8"


def _load_html(url: str, timeout: float, max_bytes: int) -> tuple[str,bytes,str]:
    _validate_public_url(url);opener=build_opener(_PublicRedirect())
    request=Request(url,headers={
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":"en-GB,en;q=0.9",
        "Accept-Encoding":"identity",
    })
    with opener.open(request,timeout=timeout) as response:
        length=response.headers.get("Content-Length")
        if length and int(length)>max_bytes:raise RuntimeError("Web page exceeds the configured size limit.")
        payload=response.read(max_bytes+1)
        if len(payload)>max_bytes:raise RuntimeError("Web page exceeds the configured size limit.")
        return response.geturl(),payload,response.headers.get("Content-Type") or ""


def load_public_html(url:str,timeout:float,max_bytes:int=2_000_000)->tuple[str,bytes,str]:
    return _load_html(url,timeout,max_bytes)


def load_public_binary(url:str,timeout:float,max_bytes:int=5_000_000)->tuple[str,bytes,str]:
    _validate_public_url(url);opener=build_opener(_PublicRedirect());request=Request(url,headers={"User-Agent":"Moriarty-V5/0.1","Accept":"image/*,application/octet-stream"})
    with opener.open(request,timeout=timeout) as response:
        length=response.headers.get("Content-Length")
        if length and int(length)>max_bytes:raise RuntimeError("Public binary exceeds the configured size limit.")
        payload=response.read(max_bytes+1)
        if len(payload)>max_bytes:raise RuntimeError("Public binary exceeds the configured size limit.")
        return response.geturl(),payload,response.headers.get("Content-Type") or ""


def _validate_public_url(url: str) -> None:
    parts=urlsplit(url)
    if parts.scheme not in {"http","https"} or not parts.hostname or parts.username or parts.password:raise ValueError("Unsafe web page URL.")
    try:addresses={item[4][0] for item in socket.getaddrinfo(parts.hostname,None)}
    except socket.gaierror as exc:raise ValueError("Web page hostname could not be resolved.") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):raise ValueError("Web page URL resolves to a non-public address.")


class _PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        _validate_public_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)
