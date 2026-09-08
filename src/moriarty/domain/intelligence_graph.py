from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Mapping


def stable_entity_id(entity_type: str, value: str, namespace: str = "") -> str:
    canonical = f"{namespace.strip().casefold()}|{entity_type.strip().casefold()}|{value.strip().casefold()}"
    return sha256(canonical.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class IntelligenceEntity:
    type: str
    value: str
    label: str
    source: str
    properties: Mapping[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", stable_entity_id(self.type, self.value, self.source))
        if not 0 <= self.confidence <= 1:
            raise ValueError("Entity confidence must be between 0 and 1.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IntelligenceRelationship:
    source_entity_id: str
    target_entity_id: str
    type: str
    source: str
    properties: Mapping[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        value = f"{self.source_entity_id}|{self.type}|{self.target_entity_id}|{self.source}"
        return sha256(value.encode("utf-8")).hexdigest()[:24]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, **asdict(self)}
