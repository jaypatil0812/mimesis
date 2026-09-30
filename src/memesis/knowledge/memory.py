"""Typed, span-backed observations and reviewable connections in the assertion ledger."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from uuid import UUID, uuid5

from memesis.domain.schemas import Assertion, EdgeType, EvidenceSpan, ExtractionMethod, NodeType, Provenance, validate_edge_endpoints
from memesis.extraction.contracts import ExtractionResult, ObservationProposal
from memesis.extraction.meaning import MEMORY_VERSION, attribution, meaning, source_family

OBSERVATION_TYPES = {
    "attributed_claim", "company_statement", "company_action", "customer_experience",
    "relationship", "interpretation", "identity_link", "belief_equivalence",
}


def observation_dict(record, repository=None):
    result = {
        "id": str(record.id), "subject_id": str(record.subject_id),
        **record.object_value, "review_state": record.review_state,
        "evidence_ids": [str(eid) for eid in record.provenance.evidence_ids],
        "evidence_span_ids": [str(sid) for sid in record.evidence_span_ids],
        "source_url": str(record.provenance.source_url),
        "published_at": record.provenance.published_at.isoformat() if record.provenance.published_at else None,
        "recorded_at": record.recorded_at.isoformat(),
        "extraction_method": record.extraction_method.value,
        "extraction_model": record.extraction_model,
    }
    if repository is not None and record.object_value.get("observation_type") == "interpretation":
        premises = [repository.get_assertion(UUID(value)) for value in record.object_value.get("context", {}).get("supporting_observation_ids", [])]
        result["support_status"] = (
            "no_explicit_premises" if not premises else
            "challenged" if any(p is None or p.review_state in {"rejected", "superseded"} for p in premises) else
            "reviewed_premises" if all(p.review_state == "accepted" for p in premises) else "candidate_premises"
        )
    return result


def observation_candidates(text: str, author_type: NodeType | None = None):
    """Generic candidate extraction, with no market-vocabulary relevance gate."""
    for match in re.finditer(r"[^\n.!?]+(?:[.!?]+|$)", text):
        raw = match.group()
        statement = raw.strip()
        if len(statement.split()) < 4 or not statement_candidate(statement):
            continue
        start = match.start() + len(raw) - len(raw.lstrip())
        mode = attribution(statement)
        if re.search(r"\b(I|we|my|our)\b.*\b(used|paid|switched|experienced|bill|latency|cost)", statement, re.I) and mode == "first_person":
            kind = "customer_experience"
        elif re.search(r"\b(launched|released|introduced|changed|raised|reduced|hired|acquired)\b", statement, re.I):
            kind = "company_action"
        elif author_type == NodeType.COMPANY:
            kind = "company_statement"
        else:
            kind = "attributed_claim"
        yield ObservationProposal(kind, start, start + len(statement), statement=statement,
                                  attribution=mode, confidence=0.5,
                                  context={"classification_basis": "rule_candidate",
                                           "requires_semantic_review": True})


def statement_candidate(statement: str) -> bool:
    return not (
        statement.endswith("?")
        or re.fullmatch(r"(?:cookie policy|accept (?:all )?cookies|privacy policy|terms of use)[.!]?", statement, re.I)
        or re.match(r"(?:sign up (?:now|for (?:our|the) newsletter)|subscribe to (?:our|the) newsletter|click here to)\b", statement, re.I)
        or statement.startswith(("http://", "https://", "```"))
    )


class ConnectedMarketMemory:
    """No name-only merges, broad market assignment, or automatic semantic promotion."""

    def __init__(self, repository):
        self.repository = repository
        self._markets = {node.id: node for node in repository.list_nodes() if node.node_type == NodeType.MARKET}

    def record(self, evidence, normalized, proposal: ObservationProposal, resolved,
               *, extraction_method=ExtractionMethod.DETERMINISTIC, model=None, prompt_version=None):
        text = normalized.normalized_text
        if proposal.observation_type not in OBSERVATION_TYPES:
            raise ValueError("unknown observation type")
        if not 0 <= proposal.start < proposal.end <= len(text):
            raise ValueError("observation offsets must refer to the normalized source")
        exact = text[proposal.start:proposal.end]
        if proposal.statement and proposal.statement != exact:
            raise ValueError("observation statement must be an exact source span")
        subject = resolved.get(proposal.subject_key)
        if subject is None:
            raise ValueError("observation subject is unresolved")
        context = dict(proposal.context)
        target = resolved.get(context.pop("target_key", None))
        supporting = []
        for value in context.get("supporting_observation_ids", []):
            record = self.repository.get_assertion(UUID(str(value)))
            if record is None or record.predicate != "MEMORY_OBSERVATION" or record.review_state in {"rejected", "superseded"}:
                raise ValueError("interpretation support must reference existing active memory observations")
            supporting.append(record)
        if proposal.observation_type == "interpretation" and not str(context.get("hypothesis", "")).strip():
            raise ValueError("an interpretation needs an explicit hypothesis in context")
        # Identity links and graph relationships must reference real local nodes.
        if proposal.observation_type in {"relationship", "identity_link", "belief_equivalence"} and target is None:
            raise ValueError("connection needs a resolved target")
        if proposal.observation_type == "relationship":
            edge_type = EdgeType(context.get("edge_type"))
            validate_edge_endpoints(edge_type, subject.node_type, target.node_type)
        mode = attribution(exact)
        if proposal.attribution != "unattributed" and proposal.attribution != mode:
            # A model cannot override quotation/criticism safety using a label.
            context["proposed_attribution"] = proposal.attribution
        family = self.family(evidence)
        ids = tuple(dict.fromkeys([subject.id] + ([target.id] if target else [])))
        provenance = Provenance(
            source_url=evidence.source_url, source_type=evidence.source_type,
            retrieved_at=evidence.retrieved_at, published_at=evidence.published_at,
            original_reference=exact, evidence_ids=(evidence.id,), confidence=proposal.confidence,
            extraction_method=extraction_method, extraction_model=model, entity_ids=ids,
        )
        span = self.repository.add_evidence_span(EvidenceSpan(
            id=uuid5(evidence.id, f"{MEMORY_VERSION}:span:{proposal.start}:{proposal.end}:{ids}:{extraction_method}:{model}:{prompt_version}"),
            normalized_document_id=normalized.id, start_offset=proposal.start,
            end_offset=proposal.end, exact_text=exact,
            content_hash=hashlib.sha256(exact.encode()).hexdigest(), provenance=provenance,
        ))
        payload = {
            "memory_version": MEMORY_VERSION, "observation_type": proposal.observation_type,
            "statement": exact, "attribution": mode, "meaning": meaning(exact),
            "contains_quotation": bool(re.search(r'["“”«»]', exact)),
            "target_id": str(target.id) if target else None, "context": context,
            "source_family": family, "confidence_semantics": "extractor score, not calibrated truth probability",
            "epistemic_status": "inferred" if proposal.observation_type == "interpretation" else "reported",
        }
        import json
        key = f"{MEMORY_VERSION}:{proposal.observation_type}:{subject.id}:{target.id if target else ''}:{proposal.start}:{proposal.end}:{model}:{prompt_version}"
        # Interpretations with different premises/hypotheses are distinct versions.
        if proposal.observation_type == "interpretation":
            key += ":" + hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
        supporting_spans = tuple(dict.fromkeys((span.id,) + tuple(sid for record in supporting for sid in record.evidence_span_ids)))
        supporting_evidence = tuple(dict.fromkeys((evidence.id,) + tuple(eid for record in supporting for eid in record.provenance.evidence_ids)))
        return self.repository.add_assertion(Assertion(
            id=uuid5(evidence.id, key), subject_id=subject.id, predicate="MEMORY_OBSERVATION",
            object_value=payload, confidence=proposal.confidence, evidence_span_ids=supporting_spans,
            extraction_method=extraction_method, extraction_model=model, prompt_version=prompt_version,
            schema_version=MEMORY_VERSION, ontology_version="memesis-0.1", review_state="proposed",
            recorded_at=datetime.now(UTC), provenance=provenance.model_copy(update={"evidence_ids": supporting_evidence}),
        ))

    def family(self, evidence):
        family = source_family(evidence)
        # A known original and its explicit syndicated copies share a family.
        origin = family["origin"]
        if family["basis"] != "exact_normalized_content":
            from memesis.extraction.meaning import canonical_url
            for item in self.repository.list_evidence():
                if item.id != evidence.id and canonical_url(str(item.source_url)) == origin:
                    original = source_family(item)
                    if original["basis"] == "exact_normalized_content":
                        family["id"] = original["id"]
                        break
        return family

    def process(self, evidence, normalized, resolved, result: ExtractionResult | None = None):
        author = resolved.get("metadata_author")
        proposals = list(observation_candidates(normalized.normalized_text, author.node_type if author else None))
        result = result or ExtractionResult()
        count = 0
        for proposal in proposals:
            self.record(evidence, normalized, proposal, resolved)
            count += 1
        for proposal in result.observations:
            self.record(evidence, normalized, proposal, resolved,
                        extraction_method=result.extraction_method, model=result.extraction_model,
                        prompt_version=result.prompt_version)
            count += 1
        # Propose documented product/company -> known market connections. A mere
        # market mention is insufficient, and these rules never approve an edge.
        subjects = [node for node in resolved.values() if getattr(node, "node_type", None) in {NodeType.PRODUCT, NodeType.COMPANY}]
        self._markets.update({node.id: node for node in resolved.values() if getattr(node, "node_type", None) == NodeType.MARKET})
        markets = self._markets.values()
        for proposal in proposals:
            statement = proposal.statement
            if not re.search(r"\b(serves|targets|designed for|built for|used for)\b", statement, re.I):
                continue
            for subject in subjects:
                if not re.search(r"(?<!\w)" + re.escape(subject.name) + r"(?!\w)", statement, re.I):
                    continue
                for market in markets:
                    if not re.search(r"(?<!\w)" + re.escape(market.name) + r"(?!\w)", statement, re.I):
                        continue
                    self.record(evidence, normalized, ObservationProposal(
                        "relationship", proposal.start, proposal.end, subject_key="subject",
                        context={"target_key": "market", "edge_type": "SERVES", "qualifiers": {
                            "basis": "explicit_names_and_service_language", "use_case_source_text": statement}},
                    ), {"subject": subject, "market": market})
                    count += 1
        # Preserve extracted relationships as independently reviewable observations.
        for relation in result.relationships:
            if relation.from_key not in resolved or relation.to_key not in resolved:
                continue
            self.record(evidence, normalized, ObservationProposal(
                "relationship", relation.start, relation.end, subject_key=relation.from_key,
                confidence=relation.confidence,
                context={"target_key": relation.to_key, "edge_type": relation.edge_type.value,
                         "qualifiers": relation.qualifiers},
            ), resolved, extraction_method=result.extraction_method,
                model=result.extraction_model, prompt_version=result.prompt_version)
            count += 1
        for belief in result.beliefs:
            node = resolved.get(belief.key)
            if node is None:
                continue
            for target_id in node.attributes.get("possible_equivalent_ids", [])[:10]:
                target = self.repository.get_node(UUID(target_id))
                if target is None:
                    continue
                self.record(evidence, normalized, ObservationProposal(
                    "belief_equivalence", belief.start, belief.end, subject_key="belief",
                    context={"target_key": "candidate", "basis": "lexical_candidate_with_matching_meaning_features"},
                ), {"belief": node, "candidate": target})
                count += 1
        return count

    def backfill(self):
        """Add memory to the existing corpus without rerunning or rewriting its old graph."""
        from memesis.extraction.deterministic import DeterministicExtractor
        count = 0
        skipped = 0
        nodes_by_evidence = {}
        for node in self.repository.list_nodes():
            if node.node_type in {NodeType.COMPANY, NodeType.PRODUCT}:
                for evidence_id in node.provenance.evidence_ids:
                    nodes_by_evidence.setdefault(evidence_id, []).append(node)
        for evidence in self.repository.list_evidence():
            if evidence.document_version_id is None:
                skipped += 1
                continue
            normalized = self.repository.get_normalized_document_for_version(evidence.document_version_id)
            if normalized is None:
                skipped += 1
                continue
            resolved = {}
            for entity in DeterministicExtractor().extract_metadata(evidence).entities:
                for identifier in entity.external_ids:
                    node = self.repository.find_node_by_identifier_value(identifier.identifier_type, identifier.value)
                    if node is not None:
                        resolved[entity.key] = node
                        break
            if "content" not in resolved:
                skipped += 1
                continue
            # Reuse only nodes actually backed by this document, not name matches
            # against the rest of the corpus.
            for node in nodes_by_evidence.get(evidence.id, []):
                resolved[f"existing:{node.id}"] = node
            count += self.process(evidence, normalized, resolved)
        annotated = 0
        superseded = 0
        restored = 0
        for record in self.repository.list_memory_assertions():
            reviews = record.object_value.get("reviews", [])
            if (record.review_state == "superseded" and reviews
                    and reviews[-1].get("reviewer") == "connected-memory-maintenance"
                    and statement_candidate(record.object_value["statement"])):
                self.repository.review_memory_assertion(record.id, "proposed", "connected-memory-maintenance",
                    "Refined boilerplate detection preserves substantive statements for review.")
                restored += 1
            if (record.object_value.get("context", {}).get("classification_basis") == "rule_candidate"
                    and record.review_state == "proposed"
                    and not statement_candidate(record.object_value["statement"])):
                self.repository.review_memory_assertion(record.id, "superseded", "connected-memory-maintenance",
                    "Question or boilerplate is not an attributable claim. Original evidence is retained.")
                superseded += 1
        evidence_by_id = {ev.id: ev for ev in self.repository.list_evidence()}
        for edge in self.repository.list_edges():
            families = sorted({self.family(evidence_by_id[eid])["id"] for eid in edge.provenance.evidence_ids if eid in evidence_by_id})
            family = "|".join(families)
            if family and edge.qualifiers.get("source_family") != family:
                self.repository.update_edge(edge.model_copy(update={"qualifiers": {**edge.qualifiers, "source_family": family}}))
                annotated += 1
        return {"observations_processed": count, "evidence_skipped": skipped, "edges_family_annotated": annotated, "nonclaim_candidates_superseded": superseded, "substantive_candidates_restored": restored,
                "note": "Candidates only; no semantic graph connections auto-approved."}

    def observations(self, *, evidence_ids=None, review_state=None):
        result = []
        for record in self.repository.list_memory_assertions(review_state=review_state):
            if evidence_ids is not None and not set(record.provenance.evidence_ids) <= set(evidence_ids):
                continue
            result.append(record)
        return result
