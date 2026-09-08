from __future__ import annotations

from typing import Protocol

from moriarty.domain.models import PhoneAnalysis


class PhoneAnalysisProvider(Protocol):
    def analyze(
        self, raw_number: str, default_region: str | None = None
    ) -> PhoneAnalysis: ...


class PhoneAnalyzer:
    """Phone analysis use case with its dependency supplied explicitly."""

    def __init__(self, provider: PhoneAnalysisProvider) -> None:
        self._provider = provider

    def analyze(
        self, raw_number: str, default_region: str | None = None
    ) -> PhoneAnalysis:
        return self._provider.analyze(raw_number, default_region)

