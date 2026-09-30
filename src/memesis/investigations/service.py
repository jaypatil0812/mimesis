"""Bounded graph exploration: explanations are reviewable hypotheses, never projections."""
import hashlib
import json
from collections import defaultdict, deque
from datetime import UTC, datetime
import httpx
from memesis.config import settings
from memesis.investigations.contracts import INVESTIGATION_VERSION, PatternCandidate, PatternResponse, Followup
from memesis.domain.schemas import EdgeType, NodeType
from uuid import UUID
from memesis.reasoning.classifier import QueryIntent, IntentType
from memesis.reasoning.decision_engine import get_decision_engine
from memesis.reasoning.market_motion import MarketMotionAnalyzer
from memesis.reasoning.packet import IntelligencePacketBuilder
from memesis.reasoning.planner import QueryPlanner
from memesis.reasoning.adapter import SYSTEM
from memesis.retrieval.context_builder import ContextBuilder
from memesis.retrieval.scope import QueryScope, ScopedGraphRepository

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

def seal_packet(packet):
    body = packet.model_dump(mode="json", exclude={"packet_hash", "estimated_tokens"})
    packet.packet_hash = digest(body)
    packet.estimated_tokens = max(len(json.dumps(body, default=str)) // 4, 1)
    return packet

def connected_path(edges, start, target, max_hops):
    """Undirected traversal preserves each edge's directed meaning in the packet."""
    if not start or not target or start == target:
        return []
    adjacency = defaultdict(list)
    for edge in edges:
        adjacency[edge["from_id"]].append((edge["to_id"], edge["id"]))
        adjacency[edge["to_id"]].append((edge["from_id"], edge["id"]))
    queue, seen = deque([(start, [])]), {start}
    while queue:
        node, path = queue.popleft()
        if len(path) >= max_hops:
            continue
        for neighbor, edge_id in adjacency[node]:
            if neighbor == target:
                return path + [edge_id]
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, path + [edge_id]))
    return []

class PatternModel:
    def __init__(self, config=None, transport=None):
        self.config, self.transport = config or settings, transport
        self.execution = {}

    def propose(self, packet, observations, seeds, config, previous_patterns=None):
        self.execution = {"status": "not_configured", "provider_call_attempted": False}
        if not self.config.model_api_key or not self.config.reason_strong_model:
            return []
        payload = {"packet": packet.model_dump(mode="json"), "observations": observations,
                   "structural_candidates": seeds, "allowed_sources": [s.source for s in config.sources],
                   "max_patterns": config.max_patterns, "max_hops": config.scope.graph_hops,
                   "previous_scoped_hypotheses": previous_patterns or []}
        encoded = json.dumps(payload, default=str)
        if len(encoded) // 4 > self.config.reasoning_max_packet_tokens:
            self.execution["status"] = "packet_too_large"
            return []
        self.execution.update(status="provider_failed", provider_call_attempted=True, model=self.config.reason_strong_model)
        prompt = SYSTEM + "\nInstead of an answer, return PatternResponse JSON. Propose possible explanations of meaningful connections, including recurring pain, belief/action sequences, competitor feature changes, messaging/experience divergence and adjacent requirements when supported. Unusual hypotheses are allowed. Do not claim these occurred just because graph nodes are connected. Use only supplied observation IDs and contiguous edge-ID paths (max_hops). Give alternative explanations, opposing evidence IDs, missing premises and a next useful question. Distinguish shared-source repetition from independent communities. Follow-up sources must be allowed_sources. Return no more than max_patterns; empty patterns is valid. Schema: " + json.dumps(PatternResponse.model_json_schema())
        try:
            with httpx.Client(timeout=self.config.reasoning_timeout_seconds, transport=self.transport, follow_redirects=False) as client:
                result = client.post(self.config.model_api_base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {self.config.model_api_key}"},
                    json={"model": self.config.reason_strong_model, "response_format": {"type": "json_object"},
                          "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": encoded}]})
                result.raise_for_status()
                self.execution["status"] = "invalid_response"
                body = result.json()
            usage = body.get("usage") or {}
            self.execution.update(usage=usage, usage_source="provider_reported" if usage else "unavailable")
            response = PatternResponse.model_validate_json(body["choices"][0]["message"]["content"])
            candidates = response.patterns
            validate_candidates(candidates, observations, packet, config)
            self.execution["status"] = "completed"
            return candidates
        except Exception as error:
            self.execution["error_type"] = type(error).__name__
            return []

def validate_candidates(candidates, observations, packet, config):
    if len(candidates) > config.max_patterns:
        raise ValueError("Pattern budget exceeded")
    known = {o["id"]: o for o in observations}
    edges = {e["id"]: e for e in packet.graph_relationships}
    evidence = {e["id"] for e in packet.primary_evidence_references}
    for candidate in candidates:
        if not set(candidate.supporting_observation_ids) <= known.keys() or not set(candidate.contradictory_evidence_ids) <= evidence:
            raise ValueError("Unknown supporting observation or opposing evidence")
        for path in candidate.connecting_paths:
            if not path or len(path) > config.scope.graph_hops or not set(path) <= edges.keys() or len(path) != len(set(path)):
                raise ValueError("Invalid connecting path")
            # Track both possible starting directions; merely sharing a node in
            # consecutive edges is insufficient to prove a traversable path.
            first = edges[path[0]]
            ends = {(first["from_id"], first["to_id"]), (first["to_id"], first["from_id"])}
            for edge_id in path[1:]:
                edge = edges[edge_id]
                ends = {(start, edge["to_id"] if end == edge["from_id"] else edge["from_id"])
                        for start, end in ends if end in {edge["from_id"], edge["to_id"]}}
            nodes = {known[oid].get(field) for oid in candidate.supporting_observation_ids for field in ("subject_id", "target_id")}
            if not any(start in nodes and end in nodes for start, end in ends):
                raise ValueError("Path does not connect supporting observations")
        if candidate.next_investigation and candidate.next_investigation.source not in {s.source for s in config.sources}:
            raise ValueError("Follow-up source is not configured")

class InvestigationService:
    def __init__(self, repository, model=None):
        self.repository, self.model = repository, model or PatternModel()

    def context(self, config, seed_evidence_ids=None):
        scope = QueryScope(**config.scope.model_dump(), as_of=datetime.now(UTC),
                           evidence_seeds=tuple(UUID(eid) for eid in seed_evidence_ids) if seed_evidence_ids is not None else None)
        view = ScopedGraphRepository(self.repository, scope)
        intent = QueryIntent(raw_query=config.question, intents=[IntentType.GENERAL_RESEARCH])
        plan = QueryPlanner.create_plan(intent)
        plan.retrieval_strategy = "investigation_graph"
        plan.target_node_types = list(NodeType)
        plan.target_edge_types = list(EdgeType)
        plan.max_hops = config.scope.graph_hops
        scoped_scores = view.compute_scores()
        subgraph = ContextBuilder(view, get_decision_engine(repository=self.repository)).build_context(plan, scoped_scores, scope.as_of)
        scores = [s for s in scoped_scores if s.subject_id in subgraph.node_ids()]
        motion = MarketMotionAnalyzer().analyze(subgraph, scores, scope.as_of)
        packet = IntelligencePacketBuilder.build_packet(config.question, intent, subgraph, motion, [], scores)
        packet.coverage["research_seed_count"] = len(seed_evidence_ids) if seed_evidence_ids is not None else None
        return seal_packet(packet)

    @staticmethod
    def observations(packet):
        observations = list(packet.memory_observations)
        for e in packet.primary_evidence_references:
            observations.append({"id": "source:" + e["id"], "statement": e["text"], "observation_type": "source_passage",
                "evidence_ids": [e["id"]], "published_at": e.get("published_at"), "review_state": "source_record",
                "source_family": e.get("source_family"), "source_type": e.get("source_type")})
        known = {o["id"] for o in observations}
        for p in packet.customer_public_perception:
            if p.get("id") and p["id"] not in known:
                observations.append({**p, "id": "perception:" + p["id"], "observation_type": "perception", "review_state": "legacy_unreviewed"})
        for e in packet.graph_relationships:
            observations.append({"id": "edge:" + e["id"], "subject_id": e["from_id"], "target_id": e["to_id"],
                "statement": f"{e['from']} {e['type']} {e['to']}", "observation_type": "graph_assertion",
                "relationship_type": e["type"], "evidence_ids": e["evidence_ids"], "published_at": e["valid_from"],
                "review_state": "legacy_graph_assertion; inspect provenance"})
        return observations

    def fingerprint(self, packet, config):
        return digest({"version": INVESTIGATION_VERSION, "processing": config.processing_version,
            "evidence": packet.primary_evidence_references, "memory": packet.memory_observations,
            "relationships": packet.graph_relationships, "perceptions": packet.customer_public_perception,
            "scores": [{k: s.get(k) for k in ("type", "subject_id", "value", "formula", "evidence_ids")} for s in packet.memesis_scores]})

    def structural_candidates(self, packet, observations, config):
        candidates = []
        grouped = defaultdict(list)
        for o in observations:
            if o.get("observation_type") == "perception":
                grouped[(o.get("subject_id"), o.get("dimension"), o.get("stance"))].append(o)
        for (subject, dimension, stance), group in grouped.items():
            ids = list(dict.fromkeys(eid for o in group for eid in o.get("evidence_ids", [])))
            if len(ids) < 2:
                continue
            candidates.append(PatternCandidate(category="recurring_perception", explanation=f"Multiple stored {dimension}/{stance} observations concern the same subject {subject}; investigate whether this reflects recurring experience.",
                supporting_observation_ids=[o["id"] for o in group[:10]], alternative_explanations=["Repeated reporting or a shared source could explain repetition.", "The observed workloads may differ or the sample may be unrepresentative."],
                missing_information=["Independent experiences, communities, dates and workload comparability need verification."],
                next_investigation=self.followup(config, "Find independent experiences for this subject and dimension.")))
        temporal = [e for e in packet.graph_relationships if e["type"] == "PRECEDES"]
        for edge in temporal:
            candidates.append(PatternCandidate(category="recorded_sequence", explanation=f"A stored PRECEDES relationship links {edge['from']} to {edge['to']}; investigate the sequence and competing causes.",
                supporting_observation_ids=["edge:" + edge["id"]], connecting_paths=[[edge["id"]]], alternative_explanations=["Publication lag or a common external event could explain timing."],
                missing_information=["Temporal sequence does not prove transmission or influence; source timestamps and relationship meaning require review."],
                next_investigation=self.followup(config, "What evidence supports or contradicts influence in this recorded sequence?")))
        # Pair distinct observation meanings through actual graph paths. This
        # permits unfamiliar links without a query-keyword whitelist.
        typed = [o for o in observations if o.get("subject_id") and o.get("observation_type") not in {"graph_assertion", "source_passage"}]
        for i, first in enumerate(typed):
            for second in typed[i + 1:]:
                if len(candidates) >= config.max_patterns:
                    break
                if first.get("observation_type") == second.get("observation_type"):
                    continue
                path = connected_path(packet.graph_relationships, first["subject_id"], second["subject_id"], config.scope.graph_hops)
                if not path:
                    continue
                candidates.append(PatternCandidate(category="connected_observation_comparison",
                    explanation=f"A typed graph path connects a {first['observation_type']} and a {second['observation_type']}; compare their scope and meaning before explaining their relationship.",
                    supporting_observation_ids=[first["id"], second["id"]], connecting_paths=[path],
                    alternative_explanations=["The records may concern different conditions or simply share an entity.", "A common source or external event may explain the connection."],
                    missing_information=["Connection is established structurally; agreement, divergence, requirements and causality remain unverified."],
                    next_investigation=self.followup(config, "What qualification or counterevidence would distinguish these explanations?")))
            if len(candidates) >= config.max_patterns:
                break
        return candidates[:config.max_patterns]

    @staticmethod
    def followup(config, question):
        if not config.sources:
            return None
        source = config.sources[0]
        return Followup(question=question, query=source.query, source=source.source,
                        rationale="Revisit the configured research boundary; a more targeted query needs analyst or model formulation.")

    def investigate(self, config, packet=None, previous=None):
        packet = packet or self.context(config)
        observations = self.observations(packet)
        seeds = self.structural_candidates(packet, observations, config)
        current_ids = {e["id"] for e in packet.primary_evidence_references}
        previous_patterns = [p for p in (previous or {}).get("patterns", [])
                             if p.get("evidence_ids") and set(p["evidence_ids"]) <= current_ids]
        generated = self.model.propose(packet, observations, [c.model_dump() for c in seeds], config, previous_patterns)
        # A successful model may find that no explanation is justified. Respect
        # that result rather than restoring the structural suggestions.
        candidates = generated if self.model.execution.get("status") == "completed" else seeds
        validate_candidates(candidates, observations, packet, config)
        evidence = {e["id"]: e for e in packet.primary_evidence_references}
        observation_by_id = {o["id"]: o for o in observations}
        patterns = []
        opposing = list(dict.fromkeys(eid for item in packet.contradictory_evidence for eid in item.get("evidence_ids", [])))
        for c in candidates:
            payload = c.model_dump(mode="json")
            payload["id"] = digest(payload)
            payload["review_state"] = "proposed"
            ids = {eid for oid in c.supporting_observation_ids for eid in observation_by_id[oid].get("evidence_ids", [])}
            payload["supporting_observations"] = [observation_by_id[oid] for oid in c.supporting_observation_ids]
            payload["evidence_ids"] = sorted(ids)
            payload["source_family_count"] = len({json.dumps(evidence[eid].get("source_family"), sort_keys=True) for eid in ids if eid in evidence})
            payload["independence_status"] = "not_established_by_source_family_count"
            payload["related_opposing_evidence_ids"] = opposing
            patterns.append(payload)
        fingerprint = self.fingerprint(packet, config)
        old_ids = set((previous or {}).get("evidence_ids", []))
        ids = set(evidence)
        return {"version": INVESTIGATION_VERSION, "fingerprint": fingerprint, "packet_hash": packet.packet_hash,
            "query_scope": packet.query_scope, "coverage": packet.coverage, "patterns": patterns,
            "reasoning_execution": self.model.execution, "missing_information": packet.missing_information,
            "observations": observations, "connecting_relationships": packet.graph_relationships,
            "evidence_ids": sorted(ids), "change": {"added_evidence_ids": sorted(ids - old_ids),
                "removed_from_scope_ids": sorted(old_ids - ids), "comparison_baseline_present": previous is not None},
            "semantics": "Provisional explanations; sequence and graph connection do not establish causality."}
