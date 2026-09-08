from __future__ import annotations

from moriarty.domain.models import InvestigationQuery, ProviderOutput
from moriarty.services.phone_analyzer import PhoneAnalyzer


class PhoneInvestigationProvider:
    """Adapts Phone Analyzer to the common investigation provider contract."""

    def __init__(self, analyzer: PhoneAnalyzer) -> None:
        self._analyzer = analyzer

    @property
    def name(self) -> str:
        return "phone_analyzer"

    def investigate(self, query: InvestigationQuery) -> ProviderOutput:
        result = self._analyzer.analyze(query.phone_number, query.default_region)
        return ProviderOutput(data=result.to_dict())
