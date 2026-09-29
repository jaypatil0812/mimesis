"""Offline, manually inspectable Phase 3 extraction evaluation."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from memesis.db.session import initialize_schema, make_engine, make_session_factory
from memesis.domain.schemas import (
    Document,
    DocumentVersion,
    Evidence,
    ExtractionMethod,
    NormalizedDocument,
    Provenance,
    Source,
)
from memesis.extraction.deterministic import DeterministicExtractor
from memesis.extraction.pipeline import EvidenceGraphPipeline
from memesis.extraction.resolution import normalize_alias
from memesis.graph.sql_repository import SqlGraphRepository


def _score(expected: Counter[str], predicted: Counter[str]) -> tuple[int, int, int]:
    true_positive = sum((expected & predicted).values())
    return (
        true_positive,
        sum(predicted.values()) - true_positive,
        sum(expected.values()) - true_positive,
    )


def _metrics(counts: tuple[int, int, int]) -> dict[str, float | int]:
    true_positive, false_positive, false_negative = counts
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


async def evaluate_phase3(dataset_path: Path) -> dict[str, Any]:
    dataset = json.loads(dataset_path.read_text())
    examples = dataset["examples"]
    extractor = DeterministicExtractor()
    entity_counts = [0, 0, 0]
    belief_counts = [0, 0, 0]
    relationship_counts = [0, 0, 0]
    mismatches: list[dict[str, Any]] = []
    token_usage: list[dict[str, int | str]] = []

    extracted: dict[str, Any] = {}
    for example in examples:
        evidence = _fixture_evidence(example)
        result = extractor.extract(evidence)
        extracted[example["id"]] = result
        predicted_entities = Counter(
            f"{entity.node_type.value}:{entity.name}"
            for entity in result.entities
            if entity.node_type.value != "Content"
        )
        predicted_beliefs = Counter(belief.proposition for belief in result.beliefs)
        predicted_relationships = Counter(
            relationship.edge_type.value for relationship in result.relationships
        )
        expected_entities = Counter(example["entities"])
        expected_beliefs = Counter(example["beliefs"])
        expected_relationships = Counter(example["relationships"])
        for aggregate, expected, predicted in (
            (entity_counts, expected_entities, predicted_entities),
            (belief_counts, expected_beliefs, predicted_beliefs),
            (relationship_counts, expected_relationships, predicted_relationships),
        ):
            values = _score(expected, predicted)
            for index, value in enumerate(values):
                aggregate[index] += value
        if (
            predicted_entities != expected_entities
            or predicted_beliefs != expected_beliefs
            or predicted_relationships != expected_relationships
        ):
            mismatches.append(
                {
                    "id": example["id"],
                    "expected": {
                        "entities": list(expected_entities.elements()),
                        "beliefs": list(expected_beliefs.elements()),
                        "relationships": list(expected_relationships.elements()),
                    },
                    "predicted": {
                        "entities": list(predicted_entities.elements()),
                        "beliefs": list(predicted_beliefs.elements()),
                        "relationships": list(predicted_relationships.elements()),
                    },
                }
            )
        candidate_chars = sum(end - start for start, end in result.ambiguous_spans)
        token_usage.append(
            {
                "id": example["id"],
                "actual_llm_tokens": 0,
                "estimated_fallback_tokens": (candidate_chars + 3) // 4,
            }
        )

    repository = _evaluation_repository()
    for example in examples:
        _persist_fixture(repository, example)
    graph_report = await EvidenceGraphPipeline(repository).run()
    resolution_results = []
    for check in dataset["resolution_checks"]:
        nodes = repository.find_nodes_by_alias(normalize_alias(check["alias"]), check["node_type"])
        resolution_results.append(
            {
                **check,
                "actual_node_count": len({node.id for node in nodes}),
                "passed": len({node.id for node in nodes}) == check["expected_node_count"],
            }
        )

    total_tokens = sum(int(item["actual_llm_tokens"]) for item in token_usage)
    estimated_tokens = sum(int(item["estimated_fallback_tokens"]) for item in token_usage)
    return {
        "dataset": str(dataset_path),
        "examples": len(examples),
        "entity_extraction": _metrics(tuple(entity_counts)),
        "entity_resolution_quality": {
            "checks_passed": sum(int(item["passed"]) for item in resolution_results),
            "checks_total": len(resolution_results),
            "quality": round(
                sum(int(item["passed"]) for item in resolution_results) / len(resolution_results), 4
            ),
            "checks": resolution_results,
        },
        "belief_extraction": _metrics(tuple(belief_counts)),
        "relationship_extraction": _metrics(tuple(relationship_counts)),
        "token_usage": {
            "actual_llm_tokens": total_tokens,
            "actual_llm_tokens_per_evidence": round(total_tokens / len(examples), 2),
            "estimated_fallback_tokens": estimated_tokens,
            "estimated_fallback_tokens_per_evidence": round(estimated_tokens / len(examples), 2),
            "per_evidence": token_usage,
        },
        "graph_projection": graph_report.as_metrics(),
        "graph_storage": repository.storage_metrics(),
        "mismatches": mismatches,
    }


def _fixture_evidence(example: dict[str, Any]) -> Evidence:
    text = example["text"]
    metadata = dict(example.get("metadata", {}))
    source_type = (
        "openalex"
        if metadata.get("openalex_resource")
        else ("bluesky" if metadata.get("did") else "fixture")
    )
    return Evidence(
        source_id=uuid4(),
        source_url=f"https://example.org/{example['id']}",
        source_type=source_type,
        retrieved_at=datetime.now(UTC),
        published_at=datetime(2026, 9, 29, tzinfo=UTC),
        original_reference=(text[:280] or example["id"]),
        raw_text=text,
        normalized_text=text,
        content_hash=sha256(text.encode()).hexdigest(),
        external_id=example["id"],
        metadata=metadata,
    )


def _evaluation_repository() -> SqlGraphRepository:
    engine = make_engine("sqlite://")
    initialize_schema(engine)
    return SqlGraphRepository(make_session_factory(engine))


def _persist_fixture(repository: SqlGraphRepository, example: dict[str, Any]) -> None:
    now = datetime.now(UTC)
    text = example["text"]
    source = repository.add_source(
        Source(
            source_key=f"eval:{example['id']}",
            source_type="evaluation_fixture",
            base_url=f"https://example.org/{example['id']}",
        )
    )
    document = repository.add_document(
        Document(
            source_id=source.id,
            external_id=example["id"],
            canonical_url=f"https://example.org/{example['id']}",
        )
    )
    version = repository.add_document_version(
        DocumentVersion(
            document_id=document.id,
            content_hash=sha256(text.encode()).hexdigest(),
            raw_payload=text,
            retrieved_at=now,
            published_at=datetime(2026, 9, 29, tzinfo=UTC),
        )
    )
    evidence = repository.add_evidence(
        Evidence(
            source_id=source.id,
            document_version_id=version.id,
            source_url=f"https://example.org/{example['id']}",
            source_type=(
                "openalex"
                if example.get("metadata", {}).get("openalex_resource")
                else "bluesky"
                if example.get("metadata", {}).get("did")
                else "fixture"
            ),
            retrieved_at=now,
            published_at=datetime(2026, 9, 29, tzinfo=UTC),
            original_reference=text[:280] or example["id"],
            raw_text=text,
            normalized_text=text,
            content_hash=sha256(text.encode()).hexdigest(),
            external_id=example["id"],
            metadata=example.get("metadata", {}),
        )
    )
    provenance = Provenance(
        source_url=evidence.source_url,
        source_type=evidence.source_type,
        retrieved_at=now,
        published_at=evidence.published_at,
        original_reference=evidence.original_reference,
        evidence_ids=(evidence.id,),
        confidence=1.0,
        extraction_method=ExtractionMethod.DETERMINISTIC,
    )
    repository.add_normalized_document(
        NormalizedDocument(
            document_version_id=version.id,
            normalizer_version="phase3-eval-v1",
            normalized_text=text,
            content_hash=sha256(text.encode()).hexdigest(),
            provenance=provenance,
        )
    )


def evaluate_phase3_sync(dataset_path: Path) -> dict[str, Any]:
    return asyncio.run(evaluate_phase3(dataset_path))
