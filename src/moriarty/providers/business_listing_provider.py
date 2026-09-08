from __future__ import annotations
from dataclasses import asdict
from moriarty.domain.models import Evidence,InvestigationQuery,ProviderOutput,Source
from moriarty.providers.osm_business import OsmBusinessClient
from moriarty.providers.wikidata_business import WikidataBusinessClient
from moriarty.providers.firma_fihristi_business import FirmaFihristiBusinessClient
from moriarty.providers.got_my_number_business import GotMyNumberBusinessClient
from moriarty.providers.telefon_org_business import TelefonOrgBusinessClient
from moriarty.providers.das_oertliche_business import DasOertlicheBusinessClient
from moriarty.providers.das_telefonbuch_business import DasTelefonbuchBusinessClient

class OsmBusinessProvider:
    def __init__(self,client:OsmBusinessClient)->None:self._client=client
    @property
    def name(self)->str:return "business_listings:osm_overpass"
    def investigate(self,query:InvestigationQuery)->ProviderOutput:
        result=self._client.lookup(query.phone_number,query.default_region)
        evidence=tuple(Evidence(kind="public_business_listing",value=item.name,source=Source(provider=self.name,url=item.source_url),confidence=.9,attributes={"category":item.category,"address":item.address,"phone":item.phone,"website":item.website,"latitude":item.latitude,"longitude":item.longitude}) for item in result.listings)
        return ProviderOutput(data={"source":result.source,"number":result.number,"count":len(result.listings),"listings":tuple(asdict(item) for item in result.listings)},evidence=evidence)

class WikidataBusinessProvider:
    def __init__(self,client:WikidataBusinessClient)->None:self._client=client
    @property
    def name(self)->str:return "business_listings:wikidata"
    def investigate(self,query:InvestigationQuery)->ProviderOutput:
        result=self._client.lookup(query.phone_number,query.default_region)
        evidence=tuple(Evidence(kind="public_business_listing",value=item.name,source=Source(provider=self.name,url=item.source_url),confidence=.9,attributes={"category":item.category,"phone":item.phone,"website":item.website,"latitude":item.latitude,"longitude":item.longitude}) for item in result.listings)
        return ProviderOutput(data={"source":result.source,"number":result.number,"count":len(result.listings),"listings":tuple(asdict(item) for item in result.listings)},evidence=evidence)

class FirmaFihristiBusinessProvider:
    def __init__(self,client:FirmaFihristiBusinessClient)->None:self._client=client
    @property
    def name(self)->str:return "business_listings:firma_fihristi_tr"
    def investigate(self,query:InvestigationQuery)->ProviderOutput:
        result=self._client.lookup(query.phone_number,query.default_region)
        evidence=tuple(Evidence(kind="public_business_listing",value=item.name,source=Source(provider=self.name,url=item.source_url),confidence=.9,attributes={"category":item.category,"address":item.address,"phone":item.phone,"website":item.website}) for item in result.listings)
        return ProviderOutput(data={"source":result.source,"number":result.number,"count":len(result.listings),"listings":tuple(asdict(item) for item in result.listings)},evidence=evidence)

class GotMyNumberBusinessProvider:
    def __init__(self,client:GotMyNumberBusinessClient)->None:self._client=client
    @property
    def name(self)->str:return "business_listings:got_my_number_uk"
    def investigate(self,query:InvestigationQuery)->ProviderOutput:
        result=self._client.lookup(query.phone_number,query.default_region)
        evidence=tuple(Evidence(kind="verified_public_business_listing",value=item.name,source=Source(provider=self.name,url=item.source_url),confidence=.95,attributes={"category":item.category,"phone":item.phone}) for item in result.listings)
        return ProviderOutput(data={"source":result.source,"number":result.number,"count":len(result.listings),"listings":tuple(asdict(item) for item in result.listings)},evidence=evidence)

class TelefonOrgBusinessProvider:
    def __init__(self,client:TelefonOrgBusinessClient)->None:self._client=client
    @property
    def name(self)->str:return "business_listings:telefon_org_tr"
    def investigate(self,query:InvestigationQuery)->ProviderOutput:
        result=self._client.lookup(query.phone_number,query.default_region)
        evidence=tuple(Evidence(kind="public_business_listing",value=item.name,source=Source(provider=self.name,url=item.source_url),confidence=.85,attributes={"category":item.category,"address":item.address,"phone":item.phone}) for item in result.listings)
        return ProviderOutput(data={"source":result.source,"number":result.number,"count":len(result.listings),"listings":tuple(asdict(item) for item in result.listings)},evidence=evidence)

class DasOertlicheBusinessProvider:
    def __init__(self,client:DasOertlicheBusinessClient)->None:self._client=client
    @property
    def name(self)->str:return "business_listings:das_oertliche_de"
    def investigate(self,query:InvestigationQuery)->ProviderOutput:
        result=self._client.lookup(query.phone_number,query.default_region)
        evidence=tuple(Evidence(kind="public_business_listing",value=item.name,source=Source(provider=self.name,url=item.source_url),confidence=.9,attributes={"category":item.category,"address":item.address,"phone":item.phone,"website":item.website}) for item in result.listings)
        return ProviderOutput(data={"source":result.source,"number":result.number,"count":len(result.listings),"listings":tuple(asdict(item) for item in result.listings)},evidence=evidence)

class DasTelefonbuchBusinessProvider:
    def __init__(self,client:DasTelefonbuchBusinessClient)->None:self._client=client
    @property
    def name(self)->str:return "business_listings:das_telefonbuch_de"
    def investigate(self,query:InvestigationQuery)->ProviderOutput:
        result=self._client.lookup(query.phone_number,query.default_region)
        evidence=tuple(Evidence(kind="public_business_listing",value=item.name,source=Source(provider=self.name,url=item.source_url),confidence=.9,attributes={"category":item.category,"address":item.address,"phone":item.phone}) for item in result.listings)
        return ProviderOutput(data={"source":result.source,"number":result.number,"count":len(result.listings),"listings":tuple(asdict(item) for item in result.listings)},evidence=evidence)
