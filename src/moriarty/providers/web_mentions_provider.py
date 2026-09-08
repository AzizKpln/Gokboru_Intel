from __future__ import annotations

from dataclasses import asdict

from moriarty.domain.models import InvestigationQuery, ProviderOutput
from moriarty.services.web_mentions import WebMentionsService


class WebMentionsProvider:
    def __init__(self, service: WebMentionsService) -> None:
        self._service = service

    @property
    def name(self) -> str:
        return self._service.provider_name

    def investigate(self, query: InvestigationQuery) -> ProviderOutput:
        result = self._service.discover(query.phone_number, query.default_region)
        return ProviderOutput(
            data={
                "queries": result.queries,
                "discovered_count": result.discovered_count,
                "count": len(result.mentions),
                "mentions": tuple(asdict(mention) for mention in result.mentions),
                "rejected": result.rejected,
            },
            evidence=self._service.evidence_for(result),
        )
