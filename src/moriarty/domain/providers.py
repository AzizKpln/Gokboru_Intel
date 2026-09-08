from __future__ import annotations

from typing import Protocol

from moriarty.domain.models import InvestigationQuery, ProviderOutput


class InvestigationProvider(Protocol):
    """Boundary implemented by every investigation module."""

    @property
    def name(self) -> str: ...

    def investigate(self, query: InvestigationQuery) -> ProviderOutput: ...
