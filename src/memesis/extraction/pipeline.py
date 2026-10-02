"""Evidence → spans → assertions → provenance-backed graph projection."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid5

from memesis.domain.schemas import (
    Assertion,
    EdgeType,
    Evidence,
    EvidenceSpan,
    ExtractionMethod,
    GraphEdge,
    NodeType,
    Provenance,
)
from memesis.extraction.contracts import (
    DETERMINISTIC_VERSION,
    SCHEMA_VERSION,
    ExtractionResult,
    StructuredExtractionModel,
)
from memesis.extraction.deterministic import DeterministicExtractor
from memesis.extraction.resolution import EntityResolver
from memesis.graph.repository import GraphRepository
from memesis.knowledge.memory import ConnectedMarketMemory
from memesis.extraction.meaning import attribution, MEMORY_VERSION

MAX_FALLBACK_CHARS = 6_000


@dataclass
class EvidenceGraphReport:
    evidence_seen: int = 0
    evidence_processed: int = 0
    extraction_cache_hits: int = 0
    entities_resolved: int = 0
    beliefs_resolved: int = 0
    assertions_written: int = 0
    edges_written: int = 0
    ambiguous_items: int = 0
    unresolved_without_model: int = 0
    llm_calls: int = 0
    strong_model_calls: int = 0
    memory_observations_processed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_metrics(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceGraphPipeline:
    def __init__(
        self,
        repository: GraphRepository,
        *,
        cheap_model: StructuredExtractionModel | None = None,
        ambiguity_model: StructuredExtractionModel | None = None,
        interpretation_version: str = "memory-worker-v1",
    ) -> None:
        self.repository = repository
        self.extractor = DeterministicExtractor()
        self.resolver = EntityResolver(repository)
        self.memory = ConnectedMarketMemory(repository)
        self.cheap_model = cheap_model
        self.ambiguity_model = ambiguity_model
        self.interpretation_version = interpretation_version

    async def run(self, *, limit: int | None = None, evidence_ids=None) -> EvidenceGraphReport:
        report = EvidenceGraphReport()
        evidence_records = self.repository.list_evidence(limit) if evidence_ids is None else [
            evidence for eid in list(evidence_ids)[:limit] if (evidence := self.repository.get_evidence(eid)) is not None]
        for evidence in evidence_records:
            # Local extraction performs synchronous database work. Yield between
            # records so a large batch cannot starve the worker lease heartbeat.
            await asyncio.sleep(0)
            report.evidence_seen += 1
            try:
                processed = await self._process(evidence, report)
                report.evidence_processed += int(processed)
            except Exception as error:
                report.failures.append(
                    {
                        "evidence_id": str(evidence.id),
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
        return report

    async def _process(self, evidence: Evidence, report: EvidenceGraphReport) -> bool:
        if evidence.document_version_id is None:
            report.failures.append({"evidence_id": str(evidence.id), "error": "Missing preserved document version"})
            return False
        normalized = self.repository.get_normalized_document_for_version(
            evidence.document_version_id
        )
        if normalized is None:
            report.failures.append({"evidence_id": str(evidence.id), "error": "Missing normalized document; normalization required"})
            return False
        cache_key = self._cache_key(
            evidence.content_hash,
            DETERMINISTIC_VERSION + ":" + self.interpretation_version,
            "|".join(
                model.model_name
                for model in (self.cheap_model, self.ambiguity_model)
                if model is not None
            )
            or None,
            "|".join(
                model.prompt_version
                for model in (self.cheap_model, self.ambiguity_model)
                if model is not None
            )
            or None,
        )
        if self.repository.has_evidence_projection(evidence.id, cache_key):
            report.extraction_cache_hits += 1
            return False

        cached = self.repository.get_extraction_cache(cache_key)
        if cached:
            report.extraction_cache_hits += 1
            cached_results = [
                ExtractionResult.from_dict(item)
                for item in dict(cached["result"]).get("results", [])
            ]
            results = [self._with_current_metadata(evidence, result) for result in cached_results]
            deterministic = results[0]
        else:
            deterministic = replace(self.extractor.extract(evidence),
                                    prompt_version=DETERMINISTIC_VERSION + ":" + self.interpretation_version)
            results = [deterministic]
        report.ambiguous_items += len(deterministic.ambiguous_spans)
        if not self.cheap_model:
            report.unresolved_without_model += len(deterministic.ambiguous_spans)
        if not cached and self.cheap_model and deterministic.ambiguous_spans:
            span_pack = [
                {
                    "start": start,
                    "end": end,
                    "text": normalized.normalized_text[start:end],
                }
                for start, end in deterministic.ambiguous_spans
            ]
            for batch in self._span_batches(span_pack):
                report.llm_calls += 1
                model_result = await self.cheap_model.extract(
                    json.dumps(batch, ensure_ascii=False),
                    context={"source_type": evidence.source_type, "offsets_are_original": True},
                )
                if model_result.extraction_method != ExtractionMethod.EXTRACTED:
                    raise ValueError("cheap model must label its result as extracted")
                if not model_result.extraction_model or not model_result.prompt_version:
                    raise ValueError("cheap model result lacks model or prompt version")
                results.append(model_result)
                report.input_tokens += model_result.input_tokens
                report.output_tokens += model_result.output_tokens
                if self.ambiguity_model and model_result.ambiguous_spans:
                    strong_pack = [
                        {
                            "start": start,
                            "end": end,
                            "text": normalized.normalized_text[start:end],
                        }
                        for start, end in model_result.ambiguous_spans
                    ]
                    for strong_batch in self._span_batches(strong_pack):
                        report.llm_calls += 1
                        report.strong_model_calls += 1
                        strong_result = await self.ambiguity_model.extract(
                            json.dumps(strong_batch, ensure_ascii=False),
                            context={
                                "source_type": evidence.source_type,
                                "offsets_are_original": True,
                                "reason": "cheap_model_unresolved",
                            },
                        )
                        if (
                            strong_result.extraction_method != ExtractionMethod.EXTRACTED
                            or not strong_result.extraction_model
                            or not strong_result.prompt_version
                        ):
                            raise ValueError("ambiguity model result lacks required lineage")
                        results.append(strong_result)
                        report.input_tokens += strong_result.input_tokens
                        report.output_tokens += strong_result.output_tokens

        resolved: dict[str, Any] = {}
        for result in results:
            self._project_result(
                evidence, normalized.id, normalized.normalized_text, result, report, resolved
            )

        if not cached:
            combined = {
                "results": [result.as_dict() for result in results],
                "ambiguous_spans": list(deterministic.ambiguous_spans),
            }
            self.repository.save_extraction_cache(
                cache_key,
                {
                    "evidence_id": evidence.id,
                    "content_hash": evidence.content_hash,
                    "extractor_version": DETERMINISTIC_VERSION + ":" + self.interpretation_version,
                    "prompt_version": results[-1].prompt_version,
                    "schema_version": SCHEMA_VERSION,
                    "model": results[-1].extraction_model,
                    "result": self._jsonable(combined),
                    "input_tokens": sum(result.input_tokens for result in results),
                    "output_tokens": sum(result.output_tokens for result in results),
                    "llm_calls": len(results) - 1,
                },
            )
        self.repository.save_evidence_projection(evidence.id, cache_key)
        return True

    def _project_result(
        self,
        evidence: Evidence,
        normalized_document_id: Any,
        normalized_text: str,
        result: ExtractionResult,
        report: EvidenceGraphReport,
        resolved: dict[str, Any],
    ) -> None:
        if result.extraction_method == ExtractionMethod.EXTRACTED:
            result = self._validated_model_result(normalized_text, result, set(resolved))
        for entity in result.entities:
            resolved[entity.key] = self.resolver.resolve_entity(
                entity,
                evidence,
                extraction_method=result.extraction_method,
                extraction_model=result.extraction_model,
            )
            report.entities_resolved += 1
        for belief in result.beliefs:
            resolved[belief.key] = self.resolver.resolve_belief(
                belief,
                evidence,
                extraction_method=result.extraction_method,
                extraction_model=result.extraction_model,
            )
            report.beliefs_resolved += 1

        spans: dict[tuple[int, int, tuple[str, ...]], EvidenceSpan] = {}
        for relation in result.relationships:
            source, target = resolved.get(relation.from_key), resolved.get(relation.to_key)
            if source is None or target is None:
                continue
            start, end = max(0, relation.start), min(len(normalized_text), relation.end)
            if end <= start:
                continue
            exact = normalized_text[start:end]
            provenance = Provenance(
                source_url=evidence.source_url,
                source_type=evidence.source_type,
                retrieved_at=evidence.retrieved_at,
                published_at=evidence.published_at,
                original_reference=evidence.original_reference,
                evidence_ids=(evidence.id,),
                confidence=relation.confidence,
                extraction_method=result.extraction_method,
                extraction_model=result.extraction_model,
                entity_ids=(source.id, target.id),
            )
            span_key = (start, end, (str(source.id), str(target.id)))
            span = spans.get(span_key)
            if span is None:
                span = self.repository.add_evidence_span(
                    EvidenceSpan(
                        normalized_document_id=normalized_document_id,
                        start_offset=start,
                        end_offset=end,
                        exact_text=exact,
                        content_hash=hashlib.sha256(exact.encode()).hexdigest(),
                        provenance=provenance,
                    )
                )
                spans[span_key] = span
            accepted = result.extraction_method == ExtractionMethod.DETERMINISTIC
            if relation.edge_type in {EdgeType.INFLUENCES, EdgeType.POSSIBLY_INFLUENCED, EdgeType.ACTS_ON}:
                accepted = False
            if relation.edge_type == EdgeType.BELIEVES and attribution(exact) != "first_person":
                accepted = False
            assertion = self.repository.add_assertion(
                Assertion(
                    id=uuid5(evidence.id, "projection:" + hashlib.sha256(json.dumps({
                        "source": str(source.id), "target": str(target.id),
                        "predicate": relation.edge_type.value, "start": start, "end": end,
                        "qualifiers": relation.qualifiers, "method": result.extraction_method.value,
                        "model": result.extraction_model, "prompt": result.prompt_version,
                    }, sort_keys=True, default=str).encode()).hexdigest()),
                    subject_id=source.id,
                    predicate=relation.edge_type.value,
                    object_value={
                        "target_id": str(target.id),
                        "qualifiers": relation.qualifiers,
                    },
                    stance=relation.qualifiers.get("stance"),
                    confidence=relation.confidence,
                    evidence_span_ids=(span.id,),
                    extraction_method=result.extraction_method,
                    extraction_model=result.extraction_model,
                    prompt_version=result.prompt_version,
                    schema_version=result.schema_version,
                    ontology_version="memesis-0.1",
                    review_state="accepted" if accepted else "proposed",
                    recorded_at=datetime.now(UTC),
                    provenance=provenance,
                )
            )
            report.assertions_written += 1
            if assertion.review_state != "accepted":
                continue
            self.repository.add_edge(
                GraphEdge(
                    edge_type=relation.edge_type,
                    from_node_id=source.id,
                    to_node_id=target.id,
                    qualifiers={
                        **relation.qualifiers,
                        "assertion_id": str(assertion.id),
                        "prompt_version": result.prompt_version,
                        "schema_version": result.schema_version,
                        "source_family": self.memory.family(evidence)["id"],
                    },
                    valid_from=evidence.published_at,
                    recorded_at=datetime.now(UTC),
                    provenance=provenance,
                )
            )
            report.edges_written += 1

        self._extract_and_record_perceptions(evidence, normalized_text, resolved)
        normalized = self.repository.get_normalized_document_for_version(evidence.document_version_id)
        if normalized is not None:
            report.memory_observations_processed += self.memory.process(evidence, normalized, resolved, result)

    def _extract_and_record_perceptions(self, evidence, normalized_text, resolved):
        from memesis.extraction.perceptions import candidates, PERCEPTION_VERSION
        normalized = self.repository.get_normalized_document_for_version(evidence.document_version_id)
        if normalized is None:
            return
        for proposal, subject in candidates(normalized_text, resolved):
            self.memory.record(evidence, normalized, proposal, {"perception_subject": subject},
                prompt_version=PERCEPTION_VERSION)
        # Candidates enter the assertion ledger. They do not automatically create
        # sentiment observations or PERCEIVES edges, and never guess an actor.

    @staticmethod
    def _cache_key(
        content_hash: str,
        extractor_version: str,
        model: str | None,
        prompt_version: str | None,
    ) -> str:
        payload = json.dumps(
            {
                "content_hash": content_hash,
                "extractor_version": extractor_version,
                "ontology": "memesis-0.1",
                "schema": SCHEMA_VERSION,
                "memory": MEMORY_VERSION,
                "model": model,
                "prompt": prompt_version,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, dict):
            return {str(key): EvidenceGraphPipeline._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [EvidenceGraphPipeline._jsonable(item) for item in value]
        return value

    @staticmethod
    def _span_batches(spans: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_chars = 0
        for span in spans:
            size = len(str(span["text"]))
            if current and current_chars + size > MAX_FALLBACK_CHARS:
                batches.append(current)
                current, current_chars = [], 0
            current.append(span)
            current_chars += size
        if current:
            batches.append(current)
        return batches

    @staticmethod
    def _validated_model_result(
        text: str, result: ExtractionResult, existing_keys: set[str]
    ) -> ExtractionResult:
        """Reject model proposals that are not exact, local, and internally connected."""

        def valid_offsets(start: int, end: int) -> bool:
            return 0 <= start < end <= len(text)

        entities = tuple(
            replace(entity, external_ids=tuple(
                identifier for identifier in entity.external_ids
                if identifier.value in text[entity.start:entity.end]
            ))
            for entity in result.entities
            if entity.node_type.value != "Content"
            and len(entity.name) <= 500
            and 0.0 <= entity.confidence <= 1.0
            and valid_offsets(entity.start, entity.end)
            and entity.name.casefold() in text[entity.start : entity.end].casefold()
        )
        beliefs = tuple(
            belief
            for belief in result.beliefs
            if 0.0 <= belief.confidence <= 1.0
            and len(belief.proposition) <= 500
            and valid_offsets(belief.start, belief.end)
            and belief.proposition == text[belief.start : belief.end]
        )
        keys = (
            existing_keys | {entity.key for entity in entities} | {belief.key for belief in beliefs}
        )
        relationships = tuple(
            relationship
            for relationship in result.relationships
            if 0.0 <= relationship.confidence <= 1.0
            and valid_offsets(relationship.start, relationship.end)
            and relationship.from_key in keys
            and relationship.to_key in keys
        )
        used = {
            key
            for relationship in relationships
            for key in (relationship.from_key, relationship.to_key)
        }
        used.update(observation.subject_key for observation in result.observations)
        used.update(observation.context.get("target_key") for observation in result.observations)
        return ExtractionResult(
            entities=tuple(entity for entity in entities if entity.key in used),
            beliefs=tuple(belief for belief in beliefs if belief.key in used),
            relationships=relationships,
            extraction_method=result.extraction_method,
            extraction_model=result.extraction_model,
            prompt_version=result.prompt_version,
            schema_version=result.schema_version,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            ambiguous_spans=result.ambiguous_spans,
            observations=tuple(
                observation for observation in result.observations
                if valid_offsets(observation.start, observation.end)
                and observation.subject_key in keys
                and observation.context.get("target_key", observation.subject_key) in keys
                and (not observation.statement or observation.statement == text[observation.start:observation.end])
            ),
        )

    def _with_current_metadata(
        self, evidence: Evidence, cached: ExtractionResult
    ) -> ExtractionResult:
        """Reuse text extraction while replacing source-specific metadata proposals."""
        metadata = self.extractor.extract_metadata(evidence)
        entities = (
            tuple(
                entity
                for entity in cached.entities
                if entity.key not in {"content", "metadata_author", "metadata_institution"}
            )
            + metadata.entities
        )
        relationships = (
            tuple(
                relationship
                for relationship in cached.relationships
                if not (
                    relationship.edge_type.value == "PUBLISHED"
                    and relationship.from_key in {"metadata_author", "metadata_institution"}
                )
            )
            + metadata.relationships
        )
        return ExtractionResult(
            entities=entities,
            beliefs=cached.beliefs,
            relationships=relationships,
            extraction_method=cached.extraction_method,
            extraction_model=cached.extraction_model,
            prompt_version=cached.prompt_version,
            schema_version=cached.schema_version,
            input_tokens=0,
            output_tokens=0,
            ambiguous_spans=cached.ambiguous_spans,
            observations=cached.observations,
        )
