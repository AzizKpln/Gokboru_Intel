from moriarty.domain.models import Evidence,InvestigationQuery,ProviderOutput,Source
from moriarty.services.disposable_number import DisposableNumberService

class DisposableNumberProvider:
 def __init__(self,service:DisposableNumberService)->None:self._service=service
 @property
 def name(self)->str:return "phone_classification:disposable_public_sms"
 def investigate(self,query:InvestigationQuery)->ProviderOutput:
  result=self._service.check(query.phone_number,query.default_region)
  evidence=tuple(Evidence("public_sms_directory_presence",result.number,Source(self.name,item["url"]),.7,{"domain":item["domain"],"classification":result.classification}) for item in result.matched_sources)
  return ProviderOutput(result.to_dict(),evidence)
