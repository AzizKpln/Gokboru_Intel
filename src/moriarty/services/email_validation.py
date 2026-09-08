from __future__ import annotations

import re
from moriarty.domain.models import EmailValidationResult
from moriarty.services.domain_intelligence import DomainIntelligenceService

_EMAIL=re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+)$",re.I)
_DISPOSABLE={"10minutemail.com","guerrillamail.com","mailinator.com","temp-mail.org","yopmail.com","sharklasers.com"}


class EmailValidationService:
    def __init__(self,domain_service:DomainIntelligenceService)->None:self._domains=domain_service
    def validate(self,email:str)->EmailValidationResult:
        cleaned=email.strip();match=_EMAIL.fullmatch(cleaned)
        if not match:return EmailValidationResult(cleaned,False,None,False,False,False,"invalid_syntax")
        domain=match.group(1).encode("idna").decode("ascii").lower();info=self._domains.analyze(domain)
        resolves=bool(info.ipv4 or info.ipv6);disposable=domain in _DISPOSABLE or any(domain.endswith("."+item) for item in _DISPOSABLE)
        status="disposable" if disposable else "mx_configured" if info.mail_configured else "domain_only" if resolves else "unresolvable"
        return EmailValidationResult(cleaned,True,domain,resolves,info.mail_configured,disposable,status)
