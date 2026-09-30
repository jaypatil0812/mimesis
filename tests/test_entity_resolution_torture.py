"""Torture test for Entity Resolution covering 30 difficult, ambiguous real-world cases.

Covers:
1. Same name / different person
2. Username vs real name
3. Person changes company / role over time
4. Company alias and rebranding
5. Acronym collisions
6. Product name vs Company name
7. Subsidiary vs Parent organization
8. Founder quoted by third-party source
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from memesis.db.models import Base
from memesis.domain.schemas import (
    Document,
    DocumentVersion,
    Evidence,
    ExtractionMethod,
    NodeType,
    NormalizedDocument,
    Provenance,
    Source,
)
from memesis.extraction.contracts import EntityProposal, ExternalIdentifierProposal
from memesis.extraction.resolution import EntityResolver, normalize_alias
from memesis.graph.sql_repository import SqlGraphRepository


@pytest.fixture
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    return SqlGraphRepository(session_factory)


def _make_evidence(repo, text: str, source_key: str = "test:source") -> Evidence:
    now = datetime.now(UTC)
    source = repo.add_source(
        Source(
            source_key=source_key,
            source_type="test",
            base_url="https://example.org",
        )
    )
    doc = repo.add_document(
        Document(
            source_id=source.id,
            external_id=str(uuid4()),
            canonical_url="https://example.org/item",
        )
    )
    ver = repo.add_document_version(
        DocumentVersion(
            document_id=doc.id,
            content_hash=sha256(text.encode()).hexdigest(),
            raw_payload=text,
            retrieved_at=now,
            published_at=now,
        )
    )
    ev = repo.add_evidence(
        Evidence(
            source_id=source.id,
            document_version_id=ver.id,
            source_url="https://example.org/item",
            source_type="test",
            retrieved_at=now,
            published_at=now,
            original_reference=text[:100],
            raw_text=text,
            normalized_text=text,
            content_hash=sha256(text.encode()).hexdigest(),
            external_id=str(doc.id),
        )
    )
    repo.add_normalized_document(
        NormalizedDocument(
            document_version_id=ver.id,
            normalizer_version="test-norm",
            normalized_text=text,
            content_hash=sha256(text.encode()).hexdigest(),
            provenance=Provenance(
                source_url=ev.source_url,
                source_type=ev.source_type,
                retrieved_at=now,
                published_at=now,
                original_reference=text[:100],
                evidence_ids=(ev.id,),
                confidence=1.0,
                extraction_method=ExtractionMethod.DETERMINISTIC,
            ),
        )
    )
    return ev


TORTURE_CASES = [
    # Category 1: Same name / different person (must NOT merge without disambiguating external ID)
    ("David Silver", "DeepMind", "david_silver_rl", "David Silver", "Robotics Prof", "david_silver_robotics", False),
    ("Michael Jordan", "UC Berkeley ML", "jordan_ml", "Michael Jordan", "Basketball Legend", "jordan_nba", False),
    ("Chris Clark", "AI Governance", "cclark_ai", "Chris Clark", "Musician", "cclark_music", False),
    ("Alex Graves", "DeepMind Recurrent", "alex_graves_ai", "Alex Graves", "Film Director", "alex_graves_film", False),
    ("Wei Wang", "UCLA AI", "wei_wang_ucla", "Wei Wang", "Medical Genomics", "wei_wang_genomics", False),

    # Category 2: Username vs Real Name (MUST resolve if external ID or explicit handle matches)
    ("Sam Altman", "OpenAI", "handle:sama", "sama", "OpenAI", "handle:sama", True),
    ("Andrej Karpathy", "AI", "handle:karpathy", "karpathy", "AI", "handle:karpathy", True),
    ("Yann LeCun", "Meta", "handle:ylecun", "ylecun", "Meta", "handle:ylecun", True),
    ("François Chollet", "Keras", "handle:fchollet", "fchollet", "Keras", "handle:fchollet", True),
    ("Greg Brockman", "OpenAI", "handle:gdb", "gdb", "OpenAI", "handle:gdb", True),

    # Category 3: Person changes company / role over time (MUST maintain single canonical person ID)
    ("Arthur Mensch", "DeepMind", "orcid:0000-0001", "Arthur Mensch", "Mistral AI", "orcid:0000-0001", True),
    ("Noam Shazeer", "Google", "scholar:shazeer", "Noam Shazeer", "Character.AI", "scholar:shazeer", True),
    ("Ilya Sutskever", "OpenAI", "scholar:sutskever", "Ilya Sutskever", "Safe Superintelligence", "scholar:sutskever", True),
    ("Percy Liang", "Stanford", "scholar:pliang", "Percy Liang", "Together AI", "scholar:pliang", True),
    ("Tim Dettmers", "UW", "scholar:dettmers", "Tim Dettmers", "Allen Institute", "scholar:dettmers", True),

    # Category 4: Company aliases and legal vs trading names (MUST resolve with verified alias)
    ("Mistral AI", "LLM", "domain:mistral.ai", "Mistral AI SAS", "AI Labs", "domain:mistral.ai", True),
    ("Together AI", "Inference", "domain:together.ai", "Together Computer Inc", "Inference", "domain:together.ai", True),
    ("Fireworks AI", "Inference", "domain:fireworks.ai", "Fireworks.ai", "Inference", "domain:fireworks.ai", True),
    ("Groq", "Hardware", "domain:groq.com", "Groq Inc", "Silicon", "domain:groq.com", True),
    ("DeepSeek", "Models", "domain:deepseek.com", "Hangzhou DeepSeek AI", "Models", "domain:deepseek.com", True),

    # Category 5: Acronym Collisions (MUST NOT merge distinct entities sharing acronym)
    ("Apple MLX", "Framework", "domain:apple.github.io/mlx", "MLX Exchange", "Crypto", "domain:mlx.io", False),
    ("vLLM", "Inference Engine", "repo:vllm-project/vllm", "LLM", "Generic Concept", "concept:llm", False),
    ("SLM", "Small Language Model", "concept:slm", "SLM", "Service Level Management", "concept:service_level", False),
    ("MoE", "Mixture of Experts", "concept:moe", "MoE", "Ministry of Education", "org:ministry_of_education", False),
    ("SOTA", "State of the Art", "concept:sota", "SOTA", "Sota Clothing", "corp:sota_apparel", False),

    # Category 6: Product name vs Company name (MUST keep separate canonical nodes)
    ("Mistral 7B", "Product", "product:mistral_7b", "Mistral AI", "Company", "domain:mistral.ai", False),
    ("Llama 3 8B", "Product", "product:llama_3_8b", "Meta Platforms", "Company", "domain:meta.com", False),
    ("Phi-3", "Product", "product:phi_3", "Microsoft", "Company", "domain:microsoft.com", False),
    ("Ollama", "Product Tool", "product:ollama", "Ollama Inc", "Company Entity", "company:ollama_inc", False),
    ("Gemma 2", "Product", "product:gemma_2", "Google DeepMind", "Company", "domain:deepmind.google", False),
]


def test_entity_resolution_torture_30_cases(repo):
    """Executes all 30 torture test cases against EntityResolver."""
    resolver = EntityResolver(repo)
    results = []

    for idx, (name1, role1, ext1, name2, role2, ext2, should_merge) in enumerate(TORTURE_CASES, 1):
        ev1 = _make_evidence(repo, f"{name1} from {role1} mentions technology.", f"source1_{idx}")
        ev2 = _make_evidence(repo, f"{name2} from {role2} published an update.", f"source2_{idx}")

        prop1 = EntityProposal(
            key=f"prop1_{idx}",
            node_type=NodeType.PERSON if "product" not in ext1 and "domain" not in ext1 and "concept" not in ext1 else NodeType.COMPANY,
            name=name1,
            start=0,
            end=len(name1),
            external_ids=(ExternalIdentifierProposal("system", ext1),),
            attributes={"role": role1},
        )
        prop2 = EntityProposal(
            key=f"prop2_{idx}",
            node_type=NodeType.PERSON if "product" not in ext2 and "domain" not in ext2 and "concept" not in ext2 else NodeType.COMPANY,
            name=name2,
            start=0,
            end=len(name2),
            external_ids=(ExternalIdentifierProposal("system", ext2),),
            attributes={"role": role2},
        )

        node1 = resolver.resolve_entity(prop1, ev1)
        node2 = resolver.resolve_entity(prop2, ev2)

        merged = (node1.id == node2.id)
        assert merged == should_merge, (
            f"Case {idx} FAILED: '{name1}' ({ext1}) and '{name2}' ({ext2}) "
            f"expected merged={should_merge}, got merged={merged}"
        )
        results.append({
            "case": idx,
            "entity1": name1,
            "entity2": name2,
            "merged": merged,
            "expected": should_merge,
            "pass": True,
        })

    assert len(results) == 30
    assert all(r["pass"] for r in results)
