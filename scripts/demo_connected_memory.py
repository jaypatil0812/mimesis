"""Reproducible before/after examples using synthetic evidence and isolated SQLite.

Run: uv run python scripts/demo_connected_memory.py
The old behavior is loaded from integration commit 41386f1, never from a provider.
No production evidence is changed and no model/network calls are made.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from memesis.db.session import initialize_schema, make_engine, make_session_factory
from memesis.domain.schemas import NodeType, Source
from memesis.extraction.contracts import BeliefProposal, ObservationProposal, EntityProposal, ExternalIdentifierProposal
from memesis.extraction.deterministic import DeterministicExtractor
from memesis.extraction.meaning import meaning
from memesis.extraction.resolution import EntityResolver
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.ingestion.contracts import CollectedDocument
from memesis.ingestion.service import IngestionService
from memesis.knowledge.memory import ConnectedMarketMemory, observation_dict, observation_candidates
from memesis.knowledge.service import KnowledgeService
from memesis.retrieval.scope import QueryScope, ScopedGraphRepository


def old_module(path):
    code = subprocess.check_output(["git", "show", "41386f1:" + path]).decode("utf-8")
    scope = {"__name__": "before_memory_demo"}
    exec(compile(code, path, "exec"), scope)
    return scope


def repository():
    engine = make_engine("sqlite://")
    initialize_schema(engine)
    return SqlGraphRepository(make_session_factory(engine))


def document(repo, text, url="https://original.example/article", metadata=None):
    source = repo.add_source(Source(source_key="demo:" + url, source_type="fixture", base_url=url))
    IngestionService(repo)._persist_document(source.id, CollectedDocument(
        external_id=url, canonical_url=url, source_url=url, source_type="fixture",
        raw_payload=json.dumps({"text": text, "metadata": metadata or {}}), text=text,
        original_reference=text, retrieved_at=datetime.now(UTC),
        published_at=datetime(2026, 9, 29, tzinfo=UTC), metadata=metadata or {},
    ))
    evidence = next(e for e in repo.list_evidence() if str(e.source_url) == url)
    return evidence, repo.get_normalized_document_for_version(evidence.document_version_id)


def belief(text):
    return BeliefProposal("belief", text, 0, len(text), "supports", "predicted", "enterprise", "unspecified", 0.9)


def main():
    before = old_module("src/memesis/extraction/resolution.py")["EntityResolver"]
    old_extractor = old_module("src/memesis/extraction/deterministic.py")["DeterministicExtractor"]
    positive = "Specialized models will replace large frontier models across routine enterprise inference workloads with predictable deployment requirements and constrained budgets"
    negative = positive.replace("will replace", "will not replace")
    rows = []
    for resolver_class, label in ((before, "before"), (EntityResolver, "after")):
        repo = repository()
        ev, _ = document(repo, positive)
        opposite_ev, _ = document(repo, negative, "https://opposite.example/article")
        resolver = resolver_class(repo)
        first = resolver.resolve_belief(belief(positive), ev)
        second = resolver.resolve_belief(belief(negative), opposite_ev)
        rows.append({"version": label, "opposite_claims_merged": first.id == second.id})
    assert rows[0]["opposite_claims_merged"] and not rows[1]["opposite_claims_merged"]
    opaque_ids = []
    for resolver_class, label in ((before, "before"), (EntityResolver, "after")):
        opaque_repo = repository()
        opaque_ev, _ = document(opaque_repo, "The identifiers tenant/ceo/account and tenant/cto/account refer to distinct source accounts.")
        opaque_resolver = resolver_class(opaque_repo)
        accounts = [opaque_resolver.resolve_entity(EntityProposal(
            "account", NodeType.PERSON, "Account " + value, 0, 3,
            external_ids=(ExternalIdentifierProposal("demo_user", value),),
        ), opaque_ev) for value in ("tenant/ceo/account", "tenant/cto/account")]
        opaque_ids.append({"version": label, "different_identifiers_merged": accounts[0].id == accounts[1].id})
    assert opaque_ids[0]["different_identifiers_merged"] and not opaque_ids[1]["different_identifiers_merged"]

    repo = repository()
    quote, quote_normalized = document(repo,
        'Researcher says "I believe specialized models will replace frontier models in enterprise inference."',
        metadata={"author_handle": "reporter"})
    quoted = {}
    for extractor_class, label in ((old_extractor, "before"), (DeterministicExtractor, "after")):
        extraction = extractor_class().extract(quote)
        quoted[label] = sum(r.edge_type.value == "BELIEVES" for r in extraction.relationships)
    assert quoted["before"] > 0 and quoted["after"] == 0

    ev, normalized = document(repo,
        "AcmeCool serves the regional cold-chain market for refrigerated warehouses.",
        "https://acme.example/product")
    knowledge = KnowledgeService(repo)
    product = knowledge.create_node(NodeType.PRODUCT, "AcmeCool", ev.id)
    market = knowledge.create_node(NodeType.MARKET, "Regional cold-chain", ev.id)
    memory = ConnectedMarketMemory(repo)
    relation = memory.record(ev, normalized, ObservationProposal(
        "relationship", 0, len(normalized.normalized_text), subject_key="product",
        context={"target_key": "market", "edge_type": "SERVES", "qualifiers": {"use_case": "refrigerated warehouses"}},
    ), {"product": product, "market": market})
    proposed_edges = len(repo.list_edges())
    accepted = repo.review_memory_assertion(relation.id, "accepted", "demo reviewer", "The supplied synthetic source explicitly names the product, market and use case.")
    view = ScopedGraphRepository(repo, QueryScope(market_id=market.id))
    assert proposed_edges == 0 and len(view.list_edges()) == 1 and product.id in {n.id for n in view.list_nodes()}
    repo.review_memory_assertion(relation.id, "rejected", "demo reviewer", "Demonstrate retraction of an approved connection.")
    assert len(repo.list_edges()) == 0

    classified = []
    supporting_ids = []
    for kind, statement in [
        ("company_statement", "Our platform is cheaper for predictable workloads."),
        ("company_action", "Acme reduced the published monthly price from 40 dollars to 30 dollars."),
        ("customer_experience", "I paid 40 dollars for our warehouse workload last month."),
        ("interpretation", "The pricing changes may indicate demand for predictable costs."),
    ]:
        item, norm = document(repo, statement, "https://example.org/" + kind)
        content = EntityResolver(repo).resolve_entity(EntityProposal(
            "content", NodeType.CONTENT, statement, 0, len(statement),
            external_ids=(ExternalIdentifierProposal("demo_content", kind),),
        ), item)
        context = {"hypothesis": statement, "supporting_observation_ids": supporting_ids[:]} if kind == "interpretation" else {}
        record = memory.record(item, norm, ObservationProposal(kind, 0, len(norm.normalized_text), context=context), {"content": content})
        classified.append({"type": kind, "state": record.review_state, "epistemic_status": record.object_value["epistemic_status"]})
        repeat = memory.record(item, norm, ObservationProposal(kind, 0, len(norm.normalized_text), context=context), {"content": content})
        assert repeat.id == record.id
        if kind != "interpretation":
            supporting_ids.append(str(record.id))
        else:
            assert len(record.provenance.evidence_ids) == 4
            repo.review_memory_assertion(record.id, "accepted", "demo reviewer", "Review the hypothesis separately from its premises.")
            repo.review_memory_assertion(record.id.__class__(supporting_ids[0]), "rejected", "demo reviewer", "Demonstrate a challenged premise.")
            assert observation_dict(record, repo)["support_status"] == "challenged"

    assert list(observation_candidates("How is Groq raising more money?")) == []

    original, _ = document(repo, "Acme announces a new product for refrigerated warehouses.", "https://publisher.example/news")
    syndicated, _ = document(repo, "A news mirror repeats the Acme announcement with extra commentary.",
                              "https://mirror.example/news", {"syndicated_from": str(original.source_url)})
    assert memory.family(original)["id"] == memory.family(syndicated)["id"]

    person_a = knowledge.create_node(NodeType.PERSON, "Alex", original.id)
    person_b = knowledge.create_node(NodeType.PERSON, "Alex", original.id)
    assert person_a.id != person_b.id
    # Reviewed corroboration retains both historical nodes and redirects future resolution.
    resolver = EntityResolver(repo)
    resolver._attach_identity(person_a, EntityProposal("a", NodeType.PERSON, "Alex", 0, 4,
                              external_ids=(ExternalIdentifierProposal("demo_profile", "profile-a"),)), original)
    resolver._attach_identity(person_b, EntityProposal("b", NodeType.PERSON, "Alex", 0, 4,
                              external_ids=(ExternalIdentifierProposal("demo_profile", "profile-b"),)), original)
    identity_ev, identity_norm = document(repo, "Profile A explicitly links to Profile B as the same person's second account.", "https://profiles.example/corroboration")
    identity = memory.record(identity_ev, identity_norm, ObservationProposal("identity_link", 0, len(identity_norm.normalized_text),
                             subject_key="a", context={"target_key": "b"}), {"a": person_a, "b": person_b})
    repo.review_memory_assertion(identity.id, "accepted", "demo reviewer", "Synthetic profile corroboration is supplied in the source; names alone were not used.")
    canonical = EntityResolver(repo).resolve_entity(EntityProposal("a", NodeType.PERSON, "Alex", 0, 4,
                    external_ids=(ExternalIdentifierProposal("demo_profile", "profile-a"),)), identity_ev)
    assert canonical.id == person_b.id

    report = {
        "synthetic_examples_only": True, "baseline_commit": "41386f1",
        "negation": rows, "quoted_author_belief_edges": quoted,
        "opaque_identifiers": opaque_ids,
        "distinct_observations": classified,
        "source_family": {"before": "different publisher hosts", "after_same_family": True},
        "market_connection": {"candidate_edges": proposed_edges, "approved_edges": 1, "retracted_edges": len([e for e in repo.list_edges() if e.edge_type.value == "SERVES"]), "reviewed_record": observation_dict(accepted)},
        "claim_conditions": meaning("Specialized models may outperform only for classification workloads within 12 months."),
        "identity": {"name_only_merge": False, "reviewed_link_used_for_future_resolution": True},
        "idempotent_repeated_observation": True,
    }
    destination = Path("data/examples/connected_memory_before_after.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
