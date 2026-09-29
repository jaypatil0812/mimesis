"""Query planning for targeted, minimal subgraph retrieval."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from memesis.domain.schemas import EdgeType, NodeType, ScoreType
from memesis.reasoning.classifier import IntentType, QueryIntent


class QueryPlan(BaseModel):
    intent: QueryIntent
    target_node_types: list[NodeType]
    target_edge_types: list[EdgeType]
    required_scores: list[ScoreType]
    include_historical_analogues: bool = False
    include_counterevidence: bool = True
    include_market_motion: bool = False
    retrieval_strategy: str = "targeted_neighborhood"
    max_nodes_per_type: dict[str, int] = Field(default_factory=dict)
    max_evidence_spans: int = 50
    max_hops: int = 2
    time_filter_days: int | None = None


class QueryPlanner:
    """Produces custom query execution plans based on intent and constraints."""

    @staticmethod
    def create_plan(intent: QueryIntent) -> QueryPlan:
        primary = intent.primary_intent()

        if primary == IntentType.RAW_RETRIEVAL:
            return QueryPlan(
                intent=intent,
                target_node_types=[NodeType.CONTENT, NodeType.BELIEF],
                target_edge_types=[EdgeType.EXPRESSES, EdgeType.PUBLISHED],
                required_scores=[],
                include_historical_analogues=False,
                include_counterevidence=False,
                include_market_motion=False,
                retrieval_strategy="raw_content_scan",
                max_nodes_per_type={"Content": 50, "Belief": 10},
                max_evidence_spans=100,
                max_hops=1,
            )

        if primary == IntentType.ACTOR_ANALYSIS:
            return QueryPlan(
                intent=intent,
                target_node_types=[NodeType.PERSON, NodeType.COMPANY, NodeType.BELIEF, NodeType.CONTENT],
                target_edge_types=[
                    EdgeType.BELIEVES,
                    EdgeType.PUBLISHED,
                    EdgeType.EXPRESSES,
                    EdgeType.INFLUENCES,
                    EdgeType.AMPLIFIES,
                    EdgeType.WORKS_AT,
                ],
                required_scores=[ScoreType.ACTOR_LEAD, ScoreType.ACTOR_INFLUENCE],
                include_historical_analogues=False,
                include_counterevidence=True,
                include_market_motion=False,
                retrieval_strategy="actor_centric_subgraph",
                max_nodes_per_type={"Person": 15, "Company": 10, "Belief": 8, "Content": 25},
                max_evidence_spans=40,
                max_hops=2,
            )

        if primary == IntentType.COMPETITOR_ANALYSIS:
            return QueryPlan(
                intent=intent,
                target_node_types=[NodeType.COMPANY, NodeType.PRODUCT, NodeType.EVENT, NodeType.BELIEF],
                target_edge_types=[
                    EdgeType.BUILDS,
                    EdgeType.ACTS_ON,
                    EdgeType.PARTICIPATED_IN,
                    EdgeType.EXPRESSES,
                    EdgeType.SERVES,
                ],
                required_scores=[ScoreType.ACTION_CONVERSION],
                include_historical_analogues=False,
                include_counterevidence=True,
                include_market_motion=False,
                retrieval_strategy="competitor_action_subgraph",
                max_nodes_per_type={"Company": 10, "Product": 12, "Event": 20, "Belief": 8},
                max_evidence_spans=45,
                max_hops=2,
            )

        if primary == IntentType.PERCEPTION_ANALYSIS:
            return QueryPlan(
                intent=intent,
                target_node_types=[NodeType.CONTENT, NodeType.BELIEF, NodeType.PERSON, NodeType.PRODUCT],
                target_edge_types=[EdgeType.EXPRESSES, EdgeType.PUBLISHED, EdgeType.AMPLIFIES],
                required_scores=[ScoreType.EVIDENCE_CONFIDENCE],
                include_historical_analogues=False,
                include_counterevidence=True,
                include_market_motion=False,
                retrieval_strategy="developer_pain_subgraph",
                max_nodes_per_type={"Content": 30, "Belief": 10, "Person": 10, "Product": 5},
                max_evidence_spans=40,
                max_hops=2,
            )

        if primary == IntentType.ADJACENT_MARKET_DISCOVERY:
            return QueryPlan(
                intent=intent,
                target_node_types=[NodeType.MARKET, NodeType.PRODUCT, NodeType.COMPANY, NodeType.BELIEF],
                target_edge_types=[EdgeType.ADJACENT_TO, EdgeType.DEPENDS_ON, EdgeType.SERVES, EdgeType.BUILDS],
                required_scores=[ScoreType.EVIDENCE_CONFIDENCE],
                include_historical_analogues=True,
                include_counterevidence=False,
                include_market_motion=False,
                retrieval_strategy="market_adjacency_subgraph",
                max_nodes_per_type={"Market": 8, "Product": 10, "Company": 10, "Belief": 5},
                max_evidence_spans=35,
                max_hops=2,
            )

        if primary == IntentType.BELIEF_ANALYSIS:
            return QueryPlan(
                intent=intent,
                target_node_types=[NodeType.BELIEF, NodeType.CONTENT, NodeType.PERSON, NodeType.COMPANY],
                target_edge_types=[EdgeType.EXPRESSES, EdgeType.BELIEVES, EdgeType.AMPLIFIES, EdgeType.PUBLISHED],
                required_scores=[ScoreType.BELIEF_VELOCITY, ScoreType.BELIEF_DIVERSITY, ScoreType.EVIDENCE_CONFIDENCE],
                include_historical_analogues=False,
                include_counterevidence=True,
                include_market_motion=True,
                retrieval_strategy="belief_propagation_subgraph",
                max_nodes_per_type={"Belief": 10, "Content": 35, "Person": 15, "Company": 10},
                max_evidence_spans=50,
                max_hops=2,
            )

        if primary == IntentType.HISTORICAL_ANALOGUE:
            return QueryPlan(
                intent=intent,
                target_node_types=[NodeType.BELIEF, NodeType.EVENT, NodeType.COMPANY, NodeType.PERSON],
                target_edge_types=[EdgeType.PRECEDES, EdgeType.ACTS_ON, EdgeType.PARTICIPATED_IN, EdgeType.EXPRESSES],
                required_scores=[ScoreType.ACTOR_LEAD, ScoreType.ACTION_CONVERSION],
                include_historical_analogues=True,
                include_counterevidence=True,
                include_market_motion=False,
                retrieval_strategy="historical_sequence_subgraph",
                max_nodes_per_type={"Belief": 10, "Event": 20, "Company": 10, "Person": 12},
                max_evidence_spans=40,
                max_hops=3,
            )

        # MARKET_MOTION or STRATEGIC_DECISION or GENERAL_RESEARCH
        time_filter = 30 if intent.time_horizon == "last_30_days" else None
        return QueryPlan(
            intent=intent,
            target_node_types=[
                NodeType.BELIEF,
                NodeType.PERSON,
                NodeType.COMPANY,
                NodeType.PRODUCT,
                NodeType.MARKET,
                NodeType.EVENT,
            ],
            target_edge_types=[
                EdgeType.BELIEVES,
                EdgeType.PUBLISHED,
                EdgeType.EXPRESSES,
                EdgeType.INFLUENCES,
                EdgeType.ACTS_ON,
                EdgeType.BUILDS,
                EdgeType.SERVES,
                EdgeType.ADJACENT_TO,
                EdgeType.DEPENDS_ON,
                EdgeType.PRECEDES,
                EdgeType.PARTICIPATED_IN,
            ],
            required_scores=[
                ScoreType.ACTOR_LEAD,
                ScoreType.ACTOR_INFLUENCE,
                ScoreType.BELIEF_VELOCITY,
                ScoreType.BELIEF_DIVERSITY,
                ScoreType.ACTION_CONVERSION,
                ScoreType.EVIDENCE_CONFIDENCE,
            ],
            include_historical_analogues=True,
            include_counterevidence=True,
            include_market_motion=True,
            retrieval_strategy="comprehensive_market_motion_subgraph",
            max_nodes_per_type={
                "Belief": 10,
                "Person": 15,
                "Company": 10,
                "Product": 10,
                "Market": 5,
                "Event": 20,
            },
            max_evidence_spans=60,
            max_hops=2,
            time_filter_days=time_filter,
        )
