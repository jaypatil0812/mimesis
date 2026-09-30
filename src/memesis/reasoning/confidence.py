"""Explainable confidence derived from measurable empirical graph properties."""

from __future__ import annotations

import math
from collections import Counter
from urllib.parse import urlparse

from memesis.domain.schemas import ScoreRecord
from memesis.reasoning.contracts import ConfidenceBreakdown
from memesis.extraction.meaning import source_family
from memesis.retrieval.context_builder import MinimumSufficientSubgraph


class ConfidenceCalculator:
    """Calculates audit-backed confidence scores without relying on LLM self-assessment."""

    @staticmethod
    def compute_confidence(
        subgraph: MinimumSufficientSubgraph,
        contradictory_count: int = 0,
        scores: list[ScoreRecord] | None = None,
    ) -> ConfidenceBreakdown:
        # 1. Evidence Quantity (saturated at 15 items)
        ev_count = len(subgraph.evidence)
        qty_score = min(ev_count / 15.0, 1.0) if ev_count > 0 else 0.0

        # 2. Evidence Quality (auditability & provenance)
        if subgraph.evidence:
            explicit_count = sum(
                1 for ev in subgraph.evidence if ev.extraction_method.value in {"source_explicit", "deterministic"}
            )
            quality_score = (explicit_count + 0.8 * (ev_count - explicit_count)) / ev_count
        else:
            quality_score = 0.0

        # 3. Source Diversity (Shannon entropy of source types/hosts)
        source_families = []
        for ev in subgraph.evidence:
            host = urlparse(str(ev.source_url)).netloc or ev.source_type
            source_families.append(f"{ev.source_type}:{host}")

        if source_families:
            counts = Counter(source_families)
            total = len(source_families)
            entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())
            max_entropy = math.log2(len(counts)) if len(counts) > 1 else 1.0
            diversity_score = min(entropy / max_entropy, 1.0) if max_entropy > 0 else 0.5
        else:
            diversity_score = 0.0

        # 4. Source Independence (distinct organizations / independent actors)
        # Different actor names do not establish independent reporting.
        independent_groups = {source_family(ev)["id"] for ev in subgraph.evidence
                              if ev.metadata.get("independence_verified") is True}
        independence_score = min(len(independent_groups) / 5.0, 1.0)

        # 5. Entity Resolution Confidence
        if subgraph.nodes:
            entity_conf = sum(n.provenance.confidence for n in subgraph.nodes) / len(subgraph.nodes)
        else:
            entity_conf = 0.0

        # 6. Temporal Consistency (are recorded dates coherent?)
        dated = [ev for ev in subgraph.evidence if ev.published_at is not None]
        temporal_score = sum(ev.published_at <= ev.retrieved_at for ev in dated) / max(ev_count, 1)

        # 7. Contradictory Evidence Balance (was counter-evidence surfaced?)
        contradictory_balance = min(contradictory_count / 5.0, 1.0)

        # 8. Graph Coverage (connectivity of retained nodes)
        if subgraph.nodes:
            connected_nodes = set()
            for e in subgraph.edges:
                connected_nodes.add(e.from_node_id)
                connected_nodes.add(e.to_node_id)
            coverage_score = len(connected_nodes & subgraph.node_ids()) / len(subgraph.nodes)
        else:
            coverage_score = 0.0

        # Weighted composite score
        overall = (
            0.20 * qty_score
            + 0.15 * quality_score
            + 0.15 * diversity_score
            + 0.15 * independence_score
            + 0.10 * entity_conf
            + 0.10 * temporal_score
            + 0.05 * contradictory_balance
            + 0.10 * coverage_score
        )

        return ConfidenceBreakdown(
            overall_confidence=round(min(max(overall, 0.0), 1.0), 3),
            evidence_quantity=round(qty_score, 3),
            evidence_quality=round(quality_score, 3),
            source_diversity=round(diversity_score, 3),
            source_independence=round(independence_score, 3),
            entity_resolution_confidence=round(entity_conf, 3),
            temporal_consistency=round(temporal_score, 3),
            contradictory_evidence_balance=round(contradictory_balance, 3),
            graph_coverage=round(coverage_score, 3),
            formula=(
                "0.20*quantity + 0.15*quality + 0.15*diversity + 0.15*independence + "
                "0.10*resolution + 0.10*temporal + 0.05*counter_balance + 0.10*coverage"
            ),
        )
