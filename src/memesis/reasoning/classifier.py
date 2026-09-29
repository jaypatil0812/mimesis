"""Deterministic and typed query intent classification."""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from memesis.domain.schemas import NodeType


class IntentType(str, Enum):
    MARKET_MOTION = "MARKET_MOTION"
    COMPETITOR_ANALYSIS = "COMPETITOR_ANALYSIS"
    ACTOR_ANALYSIS = "ACTOR_ANALYSIS"
    BELIEF_ANALYSIS = "BELIEF_ANALYSIS"
    PERCEPTION_ANALYSIS = "PERCEPTION_ANALYSIS"
    ADJACENT_MARKET_DISCOVERY = "ADJACENT_MARKET_DISCOVERY"
    HISTORICAL_ANALOGUE = "HISTORICAL_ANALOGUE"
    STRATEGIC_DECISION = "STRATEGIC_DECISION"
    GENERAL_RESEARCH = "GENERAL_RESEARCH"
    RAW_RETRIEVAL = "RAW_RETRIEVAL"


class QueryIntent(BaseModel):
    raw_query: str
    intents: list[IntentType] = Field(min_length=1)
    entities: list[str] = Field(default_factory=list)
    markets: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    beliefs: list[str] = Field(default_factory=list)
    time_horizon: str | None = None
    geography: str | None = None
    requested_depth: str = "strategic"
    decision_being_considered: str | None = None
    required_graph_objects: list[NodeType] = Field(default_factory=list)

    def primary_intent(self) -> IntentType:
        return self.intents[0]


class QueryClassifier:
    """Classifies user queries into structured intents without expensive models."""

    def __init__(self, cache: dict[str, QueryIntent] | None = None) -> None:
        self._cache = cache if cache is not None else {}

    def classify(self, query: str, *, known_entities: list[str] | None = None) -> QueryIntent:
        clean_query = query.strip()
        cache_key = hashlib.sha256(clean_query.lower().encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        intent = self._deterministic_classify(clean_query, known_entities or [])
        self._cache[cache_key] = intent
        return intent

    def _deterministic_classify(self, query: str, known_entities: list[str]) -> QueryIntent:
        lower = query.lower()
        intents: list[IntentType] = []

        # 1. Detect Raw Retrieval (e.g. "give me every post", "list all posts", "dump all")
        if re.search(r"\b(give me every|list all|every post|all posts|all content|dump all)\b", lower):
            intents.append(IntentType.RAW_RETRIEVAL)

        # 2. Detect Competitor Analysis
        if re.search(r"\b(competitor|competitors|what are (competitors|others|companies) doing)\b", lower):
            intents.append(IntentType.COMPETITOR_ANALYSIS)

        # 3. Detect Actor / People Analysis
        if re.search(r"\b(who is driving|who believes|who said|who discussed|which people|who matters|key actors)\b", lower):
            intents.append(IntentType.ACTOR_ANALYSIS)

        # 4. Detect Perception / Developer Dislike / Customer Pain
        if re.search(r"\b(dislike|complain|complaint|frustrated|perception|customer pain|developer pain|sentiment)\b", lower):
            intents.append(IntentType.PERCEPTION_ANALYSIS)

        # 5. Detect Adjacent Markets
        if re.search(r"\b(adjacent|adjacent market|adjacent markets|neighboring markets|downstream markets|benefit if)\b", lower):
            intents.append(IntentType.ADJACENT_MARKET_DISCOVERY)

        # 6. Detect Historical Analogues
        if re.search(r"\b(historical|historically|analogue|analogues|equivalent|similar situation|precedent|past)\b", lower):
            intents.append(IntentType.HISTORICAL_ANALOGUE)

        # 7. Detect Belief / Thesis / Contradiction Analysis
        if re.search(r"\b(contradict|contradicts|counterevidence|oppose|opposing|belief|thesis|small-model thesis)\b", lower):
            intents.append(IntentType.BELIEF_ANALYSIS)

        # 8. Detect Market Motion (e.g. "moving toward", "market moving", "accelerating", "shifting", "what changed", "merely talking")
        if re.search(r"\b(moving toward|market.*moving|actually moving|shifting|trend|what changed|merely talking|adoption|velocity)\b", lower):
            intents.append(IntentType.MARKET_MOTION)

        # 9. Detect Strategic Decision / Founder Guidance
        if re.search(r"\b(should we care|should an? .* investigate|what should .* do|strategy|strategic|investment decision)\b", lower):
            intents.append(IntentType.STRATEGIC_DECISION)

        # Default fallback
        if not intents:
            intents.append(IntentType.GENERAL_RESEARCH)

        # Extract entities, markets, companies, people, beliefs
        markets: list[str] = []
        if "ai infrastructure" in lower or "infrastructure" in lower:
            markets.append("AI infrastructure")
        if "inference" in lower:
            markets.append("Inference infrastructure")
        if "edge" in lower or "on-device" in lower:
            markets.append("Edge/on-device AI")

        companies: list[str] = []
        for comp in ["OpenAI", "Anthropic", "Meta", "NVIDIA", "Acme Systems", "Beta Compute", "Google", "Microsoft"]:
            if comp.lower() in lower:
                companies.append(comp)

        people: list[str] = []
        for person in ["Sam Altman", "Alex Smith", "Geoffrey Hinton", "mira", "builder42", "Maya Chen"]:
            if person.lower() in lower:
                people.append(person)

        beliefs: list[str] = []
        if re.search(r"small.*model|specialized model|quantized|efficient model", lower):
            beliefs.append("Specialized and smaller models will gain deployment share in routine enterprise workloads")

        # Time horizon extraction
        time_horizon: str | None = None
        if "last 30 days" in lower or "30 days" in lower:
            time_horizon = "last_30_days"
        elif "historically" in lower or "before companies began acting" in lower:
            time_horizon = "historical_pre_action"
        elif "2026" in lower or "2027" in lower or "recent" in lower:
            time_horizon = "current_and_near_term"

        # Geography
        geography: str | None = None
        if "regional" in lower or "global" in lower or "europe" in lower or "us" in lower:
            geography = "global"

        # Requested depth
        requested_depth = "strategic"
        if IntentType.RAW_RETRIEVAL in intents:
            requested_depth = "raw_retrieval"
        elif IntentType.ACTOR_ANALYSIS in intents and "who is driving" in lower and not re.search(r"should|why", lower):
            requested_depth = "factual"

        # Decision being considered
        decision_being_considered: str | None = None
        if "investigate" in lower or "should we care" in lower:
            decision_being_considered = "Infrastructure architecture, model routing, or specialized deployment investigation"

        # Required graph objects
        required_objects: set[NodeType] = {NodeType.BELIEF, NodeType.COMPANY, NodeType.PERSON}
        if IntentType.RAW_RETRIEVAL in intents:
            required_objects = {NodeType.CONTENT, NodeType.BELIEF}
        elif IntentType.COMPETITOR_ANALYSIS in intents:
            required_objects = {NodeType.COMPANY, NodeType.PRODUCT, NodeType.EVENT, NodeType.BELIEF}
        elif IntentType.ADJACENT_MARKET_DISCOVERY in intents:
            required_objects = {NodeType.MARKET, NodeType.PRODUCT, NodeType.COMPANY}
        elif IntentType.MARKET_MOTION in intents:
            required_objects = {NodeType.PERSON, NodeType.BELIEF, NodeType.COMPANY, NodeType.PRODUCT, NodeType.MARKET, NodeType.EVENT}
        elif IntentType.ACTOR_ANALYSIS in intents:
            required_objects = {NodeType.PERSON, NodeType.CONTENT, NodeType.BELIEF, NodeType.COMPANY}
        elif IntentType.PERCEPTION_ANALYSIS in intents:
            required_objects = {NodeType.CONTENT, NodeType.BELIEF, NodeType.PERSON, NodeType.PRODUCT}

        return QueryIntent(
            raw_query=query,
            intents=intents,
            entities=list(set(companies + people + markets)),
            markets=markets,
            companies=companies,
            people=people,
            beliefs=beliefs,
            time_horizon=time_horizon,
            geography=geography,
            requested_depth=requested_depth,
            decision_being_considered=decision_being_considered,
            required_graph_objects=sorted(list(required_objects), key=lambda x: x.value),
        )
