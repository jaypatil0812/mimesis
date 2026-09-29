"""Conservative, evidence-backed identity and belief resolution."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from uuid import UUID

from memesis.domain.schemas import (
    CanonicalNode,
    EntityAlias,
    EntityExternalIdentifier,
    Evidence,
    ExtractionMethod,
    MergeDecision,
    NodeType,
    Provenance,
)
from memesis.extraction.contracts import BeliefProposal, EntityProposal
from memesis.graph.repository import GraphRepository
from memesis.knowledge.service import KnowledgeService

_TITLE_WORDS = {"ceo", "cto", "founder", "cofounder", "chief", "president"}


def normalize_alias(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip().lstrip("@")
    words = re.findall(r"[\w.-]+", value)
    return " ".join(word for word in words if word not in _TITLE_WORDS)


def _belief_signature(proposal: BeliefProposal) -> str:
    tokens = re.findall(r"[a-z0-9]+", proposal.proposition.casefold())
    return "|".join((" ".join(tokens), proposal.scope, proposal.modality, proposal.horizon))


def _jaccard(left: str, right: str) -> float:
    a, b = (
        set(re.findall(r"[a-z0-9]+", left.casefold())),
        set(re.findall(r"[a-z0-9]+", right.casefold())),
    )
    return len(a & b) / len(a | b) if a and b else 0.0


class EntityResolver:
    """Auto-links exact stable identifiers; aliases alone only generate candidates."""

    def __init__(self, repository: GraphRepository) -> None:
        self.repository = repository
        self.knowledge = KnowledgeService(repository)

    def resolve_entity(
        self,
        proposal: EntityProposal,
        evidence: Evidence,
        *,
        extraction_method: ExtractionMethod = ExtractionMethod.DETERMINISTIC,
        extraction_model: str | None = None,
    ) -> CanonicalNode:
        matches: dict[UUID, CanonicalNode] = {}
        for identifier in proposal.external_ids:
            existing = self.repository.find_node_by_external_identifier(
                identifier.identifier_type, normalize_alias(identifier.value)
            )
            if existing:
                matches[existing.id] = existing
        if len(matches) > 1:
            # Conflicting stable identifiers are never silently reconciled.
            proposal = EntityProposal(
                **{
                    **proposal.__dict__,
                    "external_ids": (),
                    "attributes": {**proposal.attributes, "resolution_state": "conflict_review"},
                }
            )
        node = (
            next(iter(matches.values()))
            if len(matches) == 1
            else self._new_entity(
                proposal,
                evidence,
                extraction_method=extraction_method,
                extraction_model=extraction_model,
            )
        )
        self._attach_identity(node, proposal, evidence)
        return node

    def resolve_belief(
        self,
        proposal: BeliefProposal,
        evidence: Evidence,
        *,
        extraction_method: ExtractionMethod = ExtractionMethod.DETERMINISTIC,
        extraction_model: str | None = None,
    ) -> CanonicalNode:
        signature = _belief_signature(proposal)
        existing = self.repository.find_node_by_external_identifier("belief_signature", signature)
        if existing:
            self._add_alias(existing, proposal.proposition, evidence, proposal.confidence)
            return existing
        candidates = [
            node for node in self.repository.list_nodes() if node.node_type == NodeType.BELIEF
        ]
        for candidate in candidates:
            attrs = candidate.attributes
            if (
                attrs.get("scope") == proposal.scope
                and attrs.get("modality") == proposal.modality
                and attrs.get("horizon") == proposal.horizon
                and _jaccard(candidate.name, proposal.proposition) >= 0.92
            ):
                self._add_alias(candidate, proposal.proposition, evidence, proposal.confidence)
                return candidate
        entity = EntityProposal(
            key=proposal.key,
            node_type=NodeType.BELIEF,
            name=proposal.proposition,
            start=proposal.start,
            end=proposal.end,
            aliases=(proposal.proposition,),
            confidence=proposal.confidence,
            attributes={
                "proposition": proposal.proposition,
                "scope": proposal.scope,
                "modality": proposal.modality,
                "horizon": proposal.horizon,
                "resolution_state": "resolved",
            },
        )
        node = self._new_entity(
            entity,
            evidence,
            extraction_method=extraction_method,
            extraction_model=extraction_model,
        )
        self.repository.add_external_identifier(
            EntityExternalIdentifier(
                node_id=node.id,
                identifier_type="belief_signature",
                value=signature,
                normalized_value=signature,
                confidence=proposal.confidence,
                evidence_ids=(evidence.id,),
                created_at=datetime.now(UTC),
            )
        )
        return node

    def record_reviewed_merge(
        self,
        survivor: CanonicalNode,
        absorbed: CanonicalNode,
        evidence: Evidence,
        evidence_span_id: UUID,
        *,
        decided_by: str,
    ) -> MergeDecision:
        """Record a human-authorized merge; graph rewiring remains a separate reviewed action."""
        provenance = Provenance(
            source_url=evidence.source_url,
            source_type=evidence.source_type,
            retrieved_at=evidence.retrieved_at,
            published_at=evidence.published_at,
            original_reference=evidence.original_reference,
            evidence_ids=(evidence.id,),
            confidence=1.0,
            extraction_method=ExtractionMethod.ANALYST,
            entity_ids=(survivor.id, absorbed.id),
        )
        return self.repository.add_merge_decision(
            MergeDecision(
                survivor_id=survivor.id,
                absorbed_id=absorbed.id,
                evidence_span_ids=(evidence_span_id,),
                decision="accepted",
                decided_by=decided_by,
                decided_at=datetime.now(UTC),
                provenance=provenance,
            )
        )

    def _new_entity(
        self,
        proposal: EntityProposal,
        evidence: Evidence,
        *,
        extraction_method: ExtractionMethod,
        extraction_model: str | None,
    ) -> CanonicalNode:
        state = (
            "resolved"
            if proposal.external_ids or proposal.node_type == NodeType.CONTENT
            else "candidate"
        )
        return self.knowledge.create_node(
            proposal.node_type,
            proposal.name,
            evidence.id,
            confidence=proposal.confidence,
            extraction_method=extraction_method,
            extraction_model=extraction_model,
            attributes={**proposal.attributes, "resolution_state": state},
        )

    def _attach_identity(
        self, node: CanonicalNode, proposal: EntityProposal, evidence: Evidence
    ) -> None:
        for alias in {proposal.name, *proposal.aliases}:
            if alias:
                self._add_alias(node, alias, evidence, proposal.confidence)
        for identifier in proposal.external_ids:
            self.repository.add_external_identifier(
                EntityExternalIdentifier(
                    node_id=node.id,
                    identifier_type=identifier.identifier_type,
                    value=identifier.value,
                    normalized_value=normalize_alias(identifier.value),
                    confidence=proposal.confidence,
                    evidence_ids=(evidence.id,),
                    created_at=datetime.now(UTC),
                )
            )

    def _add_alias(
        self, node: CanonicalNode, alias: str, evidence: Evidence, confidence: float
    ) -> None:
        normalized = normalize_alias(alias)
        if not normalized:
            return
        self.repository.add_entity_alias(
            EntityAlias(
                node_id=node.id,
                alias=alias,
                normalized_alias=normalized,
                source_scope=evidence.source_type,
                confidence=confidence,
                evidence_ids=(evidence.id,),
                created_at=datetime.now(UTC),
            )
        )
