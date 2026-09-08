from __future__ import annotations

from moriarty.domain.models import (
    Evidence,
    InvestigationQuery,
    LookupStatus,
    ProviderOutput,
    Source,
)
from moriarty.providers.whocalled_uk import WhoCalledUkClient
from moriarty.providers.should_i_answer_uk import ShouldIAnswerUkClient
from moriarty.providers.unknownphone import UnknownPhoneClient
from moriarty.providers.phone_spam_filter import PhoneSpamFilterClient
from moriarty.providers.eight_hundred_notes import EightHundredNotesClient
from moriarty.providers.who_calls_me import WhoCallsMeClient
from moriarty.providers.phoneya import PhoneyaClient
from moriarty.providers.clever_dialer import CleverDialerClient
from moriarty.providers.who_called_today import WhoCalledTodayClient
from moriarty.providers.kim_ariyor import KimAriyorClient

_CONFIDENCE = {
    "dangerous": 0.95,
    "harassing": 0.85,
    "unknown": 0.4,
    "neutral": 0.6,
    "safe": 0.8,
}


class WhoCalledUkProvider:
    def __init__(self, client: WhoCalledUkClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "reputation:whocalled_uk"

    def investigate(self, query: InvestigationQuery) -> ProviderOutput:
        result = self._client.lookup(query.phone_number, query.default_region)
        evidence: tuple[Evidence, ...] = ()
        if result.status is LookupStatus.FOUND and result.security_level:
            evidence = (
                Evidence(
                    kind="phone_reputation.security_level",
                    value=result.security_level,
                    source=Source(provider=self.name, url=result.url),
                    confidence=_CONFIDENCE.get(result.security_level.lower(), 0.5),
                    attributes={
                        "report_count": result.report_count,
                        "lookup_count": result.lookup_count,
                        "categories": result.categories,
                    },
                ),
            )
        return ProviderOutput(data=result.to_dict(), evidence=evidence)

class UnknownPhoneProvider:
    def __init__(self, client: UnknownPhoneClient) -> None: self._client = client
    @property
    def name(self) -> str: return "reputation:unknownphone"
    def investigate(self, query: InvestigationQuery) -> ProviderOutput:
        result = self._client.lookup(query.phone_number, query.default_region)
        evidence = ()
        if result.status is LookupStatus.FOUND and result.security_level:
            evidence = (Evidence(kind="phone_reputation.rating", value=result.security_level, source=Source(provider=self.name, url=result.url), confidence={"dangerous": .9, "spam": .8, "safe": .75}.get(result.security_level.lower(), .5), attributes={"report_count": result.report_count, "detected_call_count": result.detected_call_count, "comments": result.comments}),)
        return ProviderOutput(data=result.to_dict(), evidence=evidence)

class PhoneSpamFilterProvider:
    def __init__(self, client: PhoneSpamFilterClient) -> None: self._client = client
    @property
    def name(self) -> str: return "reputation:phone_spam_filter"
    def investigate(self, query: InvestigationQuery) -> ProviderOutput:
        result = self._client.lookup(query.phone_number, query.default_region)
        evidence = ()
        if result.status is LookupStatus.FOUND:
            evidence = (Evidence(kind="phone_reputation.community_reports", value=result.security_level or "Reported", source=Source(provider=self.name, url=result.url), confidence=.65, attributes={"report_count": result.report_count, "comments": result.comments}),)
        return ProviderOutput(data=result.to_dict(), evidence=evidence)

class EightHundredNotesProvider:
    def __init__(self, client: EightHundredNotesClient) -> None: self._client = client
    @property
    def name(self) -> str: return "reputation:800notes"
    def investigate(self, query: InvestigationQuery) -> ProviderOutput:
        result = self._client.lookup(query.phone_number, query.default_region)
        evidence = ()
        if result.status is LookupStatus.FOUND:
            evidence = (Evidence(kind="phone_reputation.community_reports", value="Reported", source=Source(provider=self.name, url=result.url), confidence=.65, attributes={"categories": result.categories, "comments": result.comments}),)
        return ProviderOutput(data=result.to_dict(), evidence=evidence)

class WhoCallsMeProvider:
    def __init__(self, client: WhoCallsMeClient) -> None: self._client = client
    @property
    def name(self) -> str: return "reputation:who_calls_me"
    def investigate(self, query: InvestigationQuery) -> ProviderOutput:
        result = self._client.lookup(query.phone_number, query.default_region)
        evidence = ()
        if result.status is LookupStatus.FOUND:
            evidence = (Evidence(kind="phone_reputation.community_reports", value="Reported", source=Source(provider=self.name, url=result.url), confidence=.65, attributes={"caller_labels": result.categories, "comments": result.comments}),)
        return ProviderOutput(data=result.to_dict(), evidence=evidence)

class PhoneyaProvider:
    def __init__(self, client: PhoneyaClient) -> None: self._client = client
    @property
    def name(self) -> str: return "reputation:phoneya"
    def investigate(self, query: InvestigationQuery) -> ProviderOutput:
        result = self._client.lookup(query.phone_number, query.default_region)
        evidence = ()
        if result.status is LookupStatus.FOUND:
            evidence = (Evidence(kind="phone_reputation.official_complaints", value="Reported", source=Source(provider=self.name, url=result.url), confidence=.8, attributes={"report_count": result.report_count, "categories": result.categories}),)
        return ProviderOutput(data=result.to_dict(), evidence=evidence)

class CleverDialerProvider:
    def __init__(self,client:CleverDialerClient)->None:self._client=client
    @property
    def name(self)->str:return "reputation:clever_dialer"
    def investigate(self,query:InvestigationQuery)->ProviderOutput:
        result=self._client.lookup(query.phone_number,query.default_region); evidence=()
        if result.status is LookupStatus.FOUND:evidence=(Evidence(kind="phone_reputation.rating",value=result.security_level or "Reported",source=Source(provider=self.name,url=result.url),confidence=.75,attributes={"rating_count":result.report_count,"categories":result.categories,"comments":result.comments}),)
        return ProviderOutput(data=result.to_dict(),evidence=evidence)

class WhoCalledTodayProvider:
 def __init__(self,client:WhoCalledTodayClient)->None:self._client=client
 @property
 def name(self)->str:return "reputation:who_called_today"
 def investigate(self,query:InvestigationQuery)->ProviderOutput:
  result=self._client.lookup(query.phone_number,query.default_region);evidence=()
  if result.status is LookupStatus.FOUND:evidence=(Evidence(kind="phone_reputation.community_reports",value=result.security_level or "Reported",source=Source(provider=self.name,url=result.url),confidence=.75,attributes={"report_count":result.report_count,"lookup_count":result.lookup_count,"categories":result.categories}),)
  return ProviderOutput(data=result.to_dict(),evidence=evidence)

class KimAriyorProvider:
 def __init__(self,client:KimAriyorClient)->None:self._client=client
 @property
 def name(self)->str:return "reputation:kim_ariyor"
 def investigate(self,query:InvestigationQuery)->ProviderOutput:
  result=self._client.lookup(query.phone_number,query.default_region);evidence=()
  if result.status is LookupStatus.FOUND:evidence=(Evidence(kind="phone_reputation.rating",value=result.security_level or "Reported",source=Source(provider=self.name,url=result.url),confidence=.8,attributes={"report_count":result.report_count,"lookup_count":result.lookup_count,"categories":result.categories,"comments":result.comments}),)
  return ProviderOutput(data=result.to_dict(),evidence=evidence)


class ShouldIAnswerUkProvider:
    def __init__(self, client: ShouldIAnswerUkClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "reputation:should_i_answer_uk"

    def investigate(self, query: InvestigationQuery) -> ProviderOutput:
        result = self._client.lookup(query.phone_number, query.default_region)
        evidence: tuple[Evidence, ...] = ()
        if result.status is LookupStatus.FOUND and result.security_level:
            evidence = (
                Evidence(
                    kind="phone_reputation.rating",
                    value=result.security_level,
                    source=Source(provider=self.name, url=result.url),
                    confidence={"negative": 0.9, "positive": 0.8, "neutral": 0.6}.get(
                        result.security_level.lower(), 0.5
                    ),
                    attributes={
                        "report_count": result.report_count,
                        "categories": result.categories,
                    },
                ),
            )
        return ProviderOutput(data=result.to_dict(), evidence=evidence)
