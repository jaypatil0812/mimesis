"""Provider-neutral structured extraction contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from memesis.domain.schemas import EdgeType, ExtractionMethod, NodeType

SCHEMA_VERSION = "phase3-v1"
DETERMINISTIC_VERSION = "deterministic-market-neutral-v7"
EXTRACT_PROMPT_VERSION = "evidence-graph-extract-v2"
AMBIGUITY_PROMPT_VERSION = "evidence-graph-ambiguity-v2"


@dataclass(frozen=True)
class ExternalIdentifierProposal:
    identifier_type: str
    value: str


@dataclass(frozen=True)
class EntityProposal:
    key: str
    node_type: NodeType
    name: str
    start: int
    end: int
    aliases: tuple[str, ...] = ()
    external_ids: tuple[ExternalIdentifierProposal, ...] = ()
    confidence: float = 1.0
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BeliefProposal:
    key: str
    proposition: str
    start: int
    end: int
    stance: str
    modality: str
    scope: str
    horizon: str
    confidence: float


@dataclass(frozen=True)
class RelationshipProposal:
    edge_type: EdgeType
    from_key: str
    to_key: str
    start: int
    end: int
    confidence: float
    qualifiers: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ObservationProposal:
    observation_type: str
    start: int
    end: int
    subject_key: str = "content"
    statement: str = ""
    attribution: str = "unattributed"
    context: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5


@dataclass(frozen=True)
class ExtractionResult:
    entities: tuple[EntityProposal, ...] = ()
    beliefs: tuple[BeliefProposal, ...] = ()
    relationships: tuple[RelationshipProposal, ...] = ()
    extraction_method: ExtractionMethod = ExtractionMethod.DETERMINISTIC
    extraction_model: str | None = None
    prompt_version: str | None = None
    schema_version: str = SCHEMA_VERSION
    input_tokens: int = 0
    output_tokens: int = 0
    ambiguous_spans: tuple[tuple[int, int], ...] = ()
    observations: tuple[ObservationProposal, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExtractionResult:
        return cls(
            entities=tuple(
                EntityProposal(
                    key=item["key"],
                    node_type=NodeType(item["node_type"]),
                    name=item["name"],
                    start=int(item["start"]),
                    end=int(item["end"]),
                    aliases=tuple(item.get("aliases", ())),
                    external_ids=tuple(
                        ExternalIdentifierProposal(**identifier)
                        for identifier in item.get("external_ids", ())
                    ),
                    confidence=float(item.get("confidence", 1.0)),
                    attributes=dict(item.get("attributes", {})),
                )
                for item in value.get("entities", ())
            ),
            beliefs=tuple(BeliefProposal(**item) for item in value.get("beliefs", ())),
            relationships=tuple(
                RelationshipProposal(
                    edge_type=EdgeType(item["edge_type"]),
                    from_key=item["from_key"],
                    to_key=item["to_key"],
                    start=int(item["start"]),
                    end=int(item["end"]),
                    confidence=float(item["confidence"]),
                    qualifiers=dict(item.get("qualifiers", {})),
                )
                for item in value.get("relationships", ())
            ),
            extraction_method=ExtractionMethod(
                value.get("extraction_method", ExtractionMethod.DETERMINISTIC.value)
            ),
            extraction_model=value.get("extraction_model"),
            prompt_version=value.get("prompt_version"),
            schema_version=value.get("schema_version", SCHEMA_VERSION),
            input_tokens=int(value.get("input_tokens", 0)),
            output_tokens=int(value.get("output_tokens", 0)),
            ambiguous_spans=tuple(
                (int(item[0]), int(item[1])) for item in value.get("ambiguous_spans", ())
            ),
            observations=tuple(ObservationProposal(**item) for item in value.get("observations", ())),
        )


class StructuredExtractionModel(Protocol):
    """Cheap structured model used only after deterministic extraction."""

    model_name: str
    prompt_version: str

    async def extract(self, text: str, *, context: dict[str, Any]) -> ExtractionResult: ...
