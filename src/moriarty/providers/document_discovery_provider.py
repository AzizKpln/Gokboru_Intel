from dataclasses import asdict
from moriarty.domain.models import Evidence,InvestigationQuery,ProviderOutput,Source
from moriarty.services.document_discovery import DocumentDiscoveryService

class DocumentDiscoveryProvider:
 def __init__(self,service:DocumentDiscoveryService)->None:self._service=service
 @property
 def name(self)->str:return self._service.provider_name
 def investigate(self,query:InvestigationQuery)->ProviderOutput:
  result=self._service.discover(query.phone_number,query.default_region)
  evidence=tuple(Evidence(kind="public_document_phone_match",value=item.title,source=Source(provider=self.name,url=item.url),confidence=item.confidence,attributes={"document_type":item.document_type,"matched_text":item.matched_text,"context":item.context,"intelligence":item.intelligence}) for item in result.findings)
  intelligence_count=sum(1 for item in result.findings if item.intelligence and item.intelligence.get("status")=="success")
  return ProviderOutput(data={"number":result.number,"queries":result.queries,"checked_count":result.checked_count,"count":len(result.findings),"intelligence_count":intelligence_count,"documents":tuple(asdict(item) for item in result.findings),"failures":result.failures},evidence=evidence)
