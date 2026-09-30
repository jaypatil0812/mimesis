"""Conservative, evidence-backed identity and belief resolution."""

from __future__ import annotations

import re
import hashlib
import json
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
from memesis.extraction.meaning import meaning

_TITLE_WORDS = {"ceo", "cto", "founder", "cofounder", "chief", "president"}


def normalize_alias(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip().lstrip("@")
    words = re.findall(r"[\w.-]+", value)
    return " ".join(word for word in words if word not in _TITLE_WORDS)


def normalize_identifier(value: str) -> str:
    # Identifiers are opaque: do not strip title words, punctuation, or case.
    # Alias normalization is for names, not identity keys.
    return unicodedata.normalize("NFKC", value).strip()


def _belief_signature(proposal: BeliefProposal) -> str:
    text = " ".join(unicodedata.normalize("NFKC", proposal.proposition).split())
    fields = (text, proposal.scope, proposal.modality, proposal.horizon)
    signature = "memory-v1|" + "|".join(fields)
    # Keep existing short identities compatible. Oversized identities use the
    # complete structured meaning; the statement and conditions remain stored.
    if len(signature) > 500:
        return "memory-v1-sha256|" + hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()
    return signature


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

    def _canonical_identity(self, node):
        redirects = {
            record.subject_id: UUID(record.object_value["target_id"])
            for record in self.repository.list_memory_assertions(review_state="accepted")
            if record.object_value.get("observation_type") == "identity_link"
        }
        visited = set()
        while node.id in redirects:
            if node.id in visited:
                raise ValueError("reviewed identity cycle")
            visited.add(node.id)
            canonical = self.repository.get_node(redirects[node.id])
            if canonical is None or canonical.node_type != node.node_type:
                raise ValueError("reviewed canonical identity is unavailable")
            node = canonical
        return node

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
            existing = self.repository.find_node_by_identifier_value(identifier.identifier_type, identifier.value)
            existing = existing or self.repository.find_node_by_external_identifier(
                identifier.identifier_type, normalize_identifier(identifier.value))
            if existing:
                if existing.node_type != proposal.node_type:
                    raise ValueError("stable identifier conflicts with the proposed entity type")
                existing = self._canonical_identity(existing)
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
        # Similarity proposes a connection; it cannot establish semantic identity.
        # Exact versioned signatures above are the only automatic belief merge.
        possible_equivalents = [
            str(candidate.id) for candidate in candidates
            if candidate.name != proposal.proposition
            and _jaccard(candidate.name, proposal.proposition) >= 0.5
            and candidate.attributes.get("scope") == proposal.scope
            and candidate.attributes.get("modality") == proposal.modality
            and candidate.attributes.get("horizon") == proposal.horizon
            and meaning(candidate.name) == meaning(proposal.proposition)
        ]
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
                "meaning": meaning(proposal.proposition),
                "possible_equivalent_ids": possible_equivalents,
                "equivalence_review_state": "proposed" if possible_equivalents else "none",
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
            existing = self.repository.find_node_by_identifier_value(identifier.identifier_type, identifier.value)
            if existing and existing.id == node.id:
                continue
            if existing and existing.id != node.id and self._canonical_identity(existing).id == node.id:
                continue  # Preserve original identifier ownership and reviewed redirect.
            self.repository.add_external_identifier(
                EntityExternalIdentifier(
                    node_id=node.id,
                    identifier_type=identifier.identifier_type,
                    value=identifier.value,
                    normalized_value=normalize_identifier(identifier.value),
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
