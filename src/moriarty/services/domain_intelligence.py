from __future__ import annotations

import json
import socket
import ssl
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from moriarty.domain.models import DomainIntelligenceResult


class DomainIntelligenceService:
    def __init__(self,timeout_seconds:float=10.0,rdap_loader=None,dns_loader=None,tls_loader=None)->None:
        if timeout_seconds<=0:raise ValueError("Domain timeout must be greater than zero.")
        self._timeout=timeout_seconds;self._rdap=rdap_loader or _rdap;self._dns=dns_loader or _dns;self._tls=tls_loader or _tls
    def analyze(self,value:str)->DomainIntelligenceResult:
        domain=_domain(value);errors=[];registered=None;created=expires=registrar=None;statuses=()
        try:
            data=self._rdap(domain,self._timeout);registered=True;statuses=tuple(str(x) for x in data.get("status",()))
            for event in data.get("events",()):
                if event.get("eventAction") in {"registration","registered"}:created=event.get("eventDate")
                if event.get("eventAction") in {"expiration","expiry"}:expires=event.get("eventDate")
            for entity in data.get("entities",()):
                if "registrar" in entity.get("roles",()):registrar=_vcard_name(entity.get("vcardArray"));break
        except HTTPError as exc:
            if exc.code==404:registered=False
            else:errors.append(f"RDAP HTTP {exc.code}")
        except Exception as exc:errors.append(f"RDAP: {str(exc) or type(exc).__name__}")
        try:ipv4,ipv6,mx=self._dns(domain,self._timeout)
        except Exception as exc:ipv4=ipv6=mx=();errors.append(f"DNS: {str(exc) or type(exc).__name__}")
        try:https_valid,cert_expiry,names=self._tls(domain,self._timeout)
        except Exception as exc:https_valid=None;cert_expiry=None;names=();errors.append(f"TLS: {str(exc) or type(exc).__name__}")
        return DomainIntelligenceResult(domain,registered,created,expires,registrar,statuses,tuple(ipv4),tuple(ipv6),tuple(mx),bool(mx),https_valid,cert_expiry,tuple(names),tuple(errors))


def _domain(value:str)->str:
    raw=value.strip();host=urlsplit(raw if "://" in raw else "//"+raw).hostname
    if not host or "." not in host:raise ValueError("A valid public domain is required.")
    return host.rstrip(".").encode("idna").decode("ascii").lower()


def _rdap(domain:str,timeout:float)->dict:
    request=Request(f"https://rdap.org/domain/{domain}",headers={"Accept":"application/rdap+json,application/json","User-Agent":"Moriarty-V5/0.1"})
    try:
        with urlopen(request,timeout=timeout) as response:return json.loads(response.read())
    except URLError as exc:raise RuntimeError(exc.reason) from exc


def _dns(domain:str,timeout:float):
    import dns.resolver
    resolver=dns.resolver.Resolver();resolver.lifetime=timeout
    def records(kind):
        try:return tuple(sorted(str(item).rstrip(".") for item in resolver.resolve(domain,kind)))
        except Exception:return ()
    mx=()
    try:mx=tuple(sorted(f"{item.preference} {str(item.exchange).rstrip('.')}" for item in resolver.resolve(domain,"MX")))
    except Exception:pass
    return records("A"),records("AAAA"),mx


def _tls(domain:str,timeout:float):
    context=ssl.create_default_context()
    with socket.create_connection((domain,443),timeout=timeout) as raw:
        with context.wrap_socket(raw,server_hostname=domain) as wrapped:cert=wrapped.getpeercert()
    expiry=cert.get("notAfter");names=tuple(sorted({value for kind,value in cert.get("subjectAltName",()) if kind=="DNS"}))
    return True,datetime.strptime(expiry,"%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc).isoformat() if expiry else None,names


def _vcard_name(vcard)->str|None:
    if not isinstance(vcard,list) or len(vcard)<2:return None
    for item in vcard[1]:
        if isinstance(item,list) and len(item)>3 and item[0] in {"fn","org"}:return str(item[3])
    return None
