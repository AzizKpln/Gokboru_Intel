from __future__ import annotations

import base64
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from moriarty.domain.models import CompanyRegistryResult


class CompaniesHouseClient:
    name="companies_house"
    def __init__(self,api_key:str|None=None,timeout_seconds:float=15.0,loader=None)->None:
        if timeout_seconds<=0:raise ValueError("Registry timeout must be greater than zero.")
        self._key=api_key or os.environ.get("COMPANIES_HOUSE_API_KEY");self._timeout=timeout_seconds;self._loader=loader or _load
    def search(self,name:str,limit:int=10)->CompanyRegistryResult:
        query=name.strip()
        if not query:raise ValueError("Company name cannot be empty.")
        if not self._key:raise RuntimeError("COMPANIES_HOUSE_API_KEY is not set.")
        url="https://api.company-information.service.gov.uk/search/companies?"+urlencode({"q":query,"items_per_page":max(1,min(limit,100))})
        auth=base64.b64encode((self._key+":").encode()).decode();payload=self._loader(url,self._timeout,auth)
        companies=[]
        for item in payload.get("items",()):
            address=item.get("address_snippet") or ""
            companies.append({"name":item.get("title"),"company_number":item.get("company_number"),"status":item.get("company_status"),"type":item.get("company_type"),"incorporated_on":item.get("date_of_creation"),"address":address,"url":"https://find-and-update.company-information.service.gov.uk/company/"+str(item.get("company_number") or "")})
        return CompanyRegistryResult(self.name,query,"GB",len(companies),tuple(companies))


def _load(url:str,timeout:float,auth:str)->dict:
    request=Request(url,headers={"Authorization":"Basic "+auth,"Accept":"application/json","User-Agent":"Moriarty-V5/0.1"})
    try:
        with urlopen(request,timeout=timeout) as response:return json.loads(response.read())
    except HTTPError as exc:raise RuntimeError(f"Companies House returned HTTP {exc.code}.") from exc
    except URLError as exc:raise RuntimeError(f"Companies House network error: {exc.reason}") from exc
