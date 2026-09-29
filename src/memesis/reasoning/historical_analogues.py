"""Historical analogue retrieval and structural pattern comparison."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from memesis.domain.schemas import EdgeType, NodeType
from memesis.retrieval.context_builder import MinimumSufficientSubgraph


class HistoricalAnalogue(BaseModel):
    analogue: str
    similarities: list[str] = Field(min_length=1)
    differences: list[str] = Field(min_length=1)
    similarity_confidence: float = Field(ge=0.0, le=1.0)
    structural_matches: dict[str, Any] = Field(default_factory=dict)
    time_lag_observed: str | None = None


class HistoricalAnalogueEngine:
    """Finds structurally similar historical situations from graph patterns and domain templates."""

    def find_analogues(
        self,
        query: str,
        subgraph: MinimumSufficientSubgraph,
    ) -> list[HistoricalAnalogue]:
        # Analyze current subgraph structural properties
        node_types = {n.node_type for n in subgraph.nodes}
        edge_types = {e.edge_type for e in subgraph.edges}

        has_beliefs = NodeType.BELIEF in node_types
        has_company_actions = EdgeType.ACTS_ON in edge_types or any(
            n.node_type == NodeType.EVENT for n in subgraph.nodes
        )
        has_routers = any("router" in n.name.lower() or "routing" in n.name.lower() for n in subgraph.nodes)
        has_quantization = any("quantiz" in n.name.lower() or "edge" in n.name.lower() for n in subgraph.nodes)

        analogues: list[HistoricalAnalogue] = []

        # Analogue 1: NLP Distillation & Specialization (BERT -> DistilBERT/RoBERTa 2019–2021)
        analogues.append(
            HistoricalAnalogue(
                analogue="NLP Distillation and Specialized Compression Shift (2019–2021)",
                similarities=[
                    "Early phase dominated by massive general models before enterprise serving unit economics forced distillation and task-specific fine-tuning.",
                    "Independent researchers and developers published cost and latency benchmarks months before major cloud vendors released optimized runtimes.",
                    "Specialized models achieved 95%+ of task accuracy on routine classification/extraction with 60–80% lower inference latency.",
                ],
                differences=[
                    "Modern frontier models exhibit emergent multi-step reasoning capabilities that small models cannot replicate without compound system architectures.",
                    "The current shift features proprietary model API providers launching their own small models and routers rather than pure open checkpoint sharing.",
                    "Hardware constraints (VRAM and KV cache bandwidth) are more acute today than CPU/GPU memory bottlenecks in 2019.",
                ],
                similarity_confidence=0.85 if has_beliefs and has_company_actions else 0.75,
                structural_matches={
                    "pattern": "monolithic_to_distilled_specialization",
                    "actor_lead_present": True,
                    "company_action_lag_months": 12,
                },
                time_lag_observed="12–18 months from research consensus to commercial runtime release",
            )
        )

        # Analogue 2: Microservices and Dynamic Layer Routing (2012–2015)
        if has_routers or "routing" in query.lower() or "infrastructure" in query.lower():
            analogues.append(
                HistoricalAnalogue(
                    analogue="Monolithic to Microservices & Dynamic Traffic Routing Transition (2012–2015)",
                    similarities=[
                        "High cost and operational blast radius of monolithic services drove adoption of specialized services with an intelligent routing layer.",
                        "Initial developer friction centered around latency overhead, observability, and managing heterogeneous micro-deployments.",
                        "Gateway/router tooling became a standalone venture-backed infrastructure layer before cloud incumbents incorporated it as a native feature.",
                    ],
                    differences=[
                        "Microservice routing is deterministic by path/header; model routing requires stochastic semantic classification and confidence estimation.",
                        "LLM weights require massive VRAM pools, creating cold-start and memory challenges unknown to stateless container microservices.",
                    ],
                    similarity_confidence=0.78,
                    structural_matches={
                        "pattern": "unbundling_with_smart_dispatch",
                        "market_modularization": True,
                    },
                    time_lag_observed="24 months from developer frustration to mature routing infrastructure",
                )
            )

        # Analogue 3: RISC vs CISC Microprocessor Specialization (1980s)
        analogues.append(
            HistoricalAnalogue(
                analogue="Hardware Architecture Specialization (RISC vs CISC Instruction Specialization, 1980s)",
                similarities=[
                    "General-purpose complex architectures faced diminishing returns on power/heat/cost per operation for routine instructions.",
                    "Stripping instructions down to essential primitives allowed dramatically faster pipelining and reduced die area/cost.",
                ],
                differences=[
                    "Software weights can be reloaded and quantized dynamically, whereas silicon architecture was locked in physical masks.",
                    "Frontier LLMs continue to expand in absolute scale for frontier tasks alongside small specialized deployments.",
                ],
                similarity_confidence=0.68,
                structural_matches={
                    "pattern": "reduced_instruction_efficiency",
                },
                time_lag_observed="Multi-year architectural coexistence rather than total displacement",
            )
        )

        return analogues
