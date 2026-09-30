"""High-precision deterministic extraction before any model call."""

from __future__ import annotations

import re
from hashlib import sha256
from typing import Any

from memesis.domain.schemas import EdgeType, Evidence, NodeType
from memesis.extraction.contracts import (
    BeliefProposal,
    EntityProposal,
    ExternalIdentifierProposal,
    ExtractionResult,
    RelationshipProposal,
)
from memesis.extraction.meaning import attribution

_BOILERPLATE = re.compile(
    r"\b(cookie policy|accept cookies|privacy policy|terms of use|sign up|subscribe|read more)\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
_ROLE = re.compile(
    r"(?P<person>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*"
    r"(?:\((?P<handle>@[A-Za-z0-9_.-]+)\))?\s*,?\s*"
    r"(?:(?:the|is)\s+)?(?P<role>(?i:CEO|CTO|founder|co-founder))\s+(?:of|at)\s+"
    r"(?P<company>[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,3})",
)
_LAUNCH = re.compile(
    r"(?P<company>[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,2})\s+"
    r"(?P<verb>released|launched|introduced|unveiled)\s+"
    r"(?P<product>[A-Z][A-Za-z0-9_.-]*(?:\s+[A-Z0-9][A-Za-z0-9_.-]*){0,4})",
)
_ATTRIBUTION = re.compile(
    r"^(?:[A-Z][A-Za-z.-]+(?:\s+[A-Z][A-Za-z.-]+){0,3}\s+)?"
    r"(?:said|says|argued|argues|believes|expects|predicts)\s+(?:that\s+)?",
    re.IGNORECASE,
)
_ATTRIBUTION_ANYWHERE = re.compile(
    r"\b(?:said|says|argued|argues|believes|expects|predicts)\s+(?:that\s+)?",
    re.IGNORECASE,
)
_PROPOSITION = re.compile(
    r"\b(will|would|should|must|can|could|may|might|likely|unlikely|"
    r"replace|replaces|reduce|reduces|increase|increases|outperform|outperforms|"
    r"enable|enables|drive|drives|become|becomes|is cheaper|are cheaper|"
    r"is faster|are faster|is better|are better)\b",
    re.IGNORECASE,
)
_EVENT_ONLY = re.compile(r"\b(released|launched|introduced|unveiled)\b", re.IGNORECASE)
_FIRST_PERSON = re.compile(r"\b(i believe|i think|we believe|we expect|we predict)\b", re.I)
_RELEVANCE = re.compile(
    r"\b(ai|model|models|inference|infrastructure|llm|compute|deployment|runtime|"
    r"frontier|specialized|quantized|edge|enterprise|claude|gpt|open weights)\b",
    re.IGNORECASE,
)
_NON_CLAIM = re.compile(
    r"^(you can|more details|click here|learn more|download|subscribe|sign up)\b",
    re.IGNORECASE,
)


def _entity_key(prefix: str, value: str) -> str:
    return f"{prefix}:{sha256(value.casefold().encode()).hexdigest()[:16]}"


class DeterministicExtractor:
    version = "deterministic-phase3-v3"

    def extract(self, evidence: Evidence) -> ExtractionResult:
        text = evidence.normalized_text or evidence.raw_text
        entities: dict[str, EntityProposal] = {}
        relationships: list[RelationshipProposal] = []
        beliefs: list[BeliefProposal] = []
        ambiguous: list[tuple[int, int]] = []

        metadata = self.extract_metadata(evidence)
        entities.update({entity.key: entity for entity in metadata.entities})
        relationships.extend(metadata.relationships)

        for match in _ROLE.finditer(text):
            person, company = match.group("person").strip(), match.group("company").strip()
            role = match.group("role").casefold()
            person_key = _entity_key("person", person)
            company_key = _entity_key("company", company)
            handle = match.group("handle")
            external_ids = (
                (ExternalIdentifierProposal("explicit_social_handle", handle.removeprefix("@")),)
                if handle
                else ()
            )
            entities[person_key] = EntityProposal(
                person_key,
                NodeType.PERSON,
                person,
                match.start("person"),
                match.end("person"),
                aliases=(
                    (handle, handle.removeprefix("@"), f"{company} {role.upper()}")
                    if handle
                    else (f"{company} {role.upper()}",)
                ),
                external_ids=external_ids,
                confidence=0.98,
                attributes={"role": role},
            )
            entities[company_key] = EntityProposal(
                company_key,
                NodeType.COMPANY,
                company,
                match.start("company"),
                match.end("company"),
                confidence=0.96,
            )
            relationships.append(
                RelationshipProposal(
                    EdgeType.FOUNDED if "founder" in role else EdgeType.WORKS_AT,
                    person_key,
                    company_key,
                    match.start(),
                    match.end(),
                    0.97,
                    {"role": role, "basis": "explicit_role_phrase"},
                )
            )

        author_key = "metadata_author" if "metadata_author" in entities else None

        for match in _LAUNCH.finditer(text):
            company = match.group("company").strip().rstrip(".,;:")
            product = match.group("product").strip().rstrip(".,;:")
            event_name = match.group(0).strip().rstrip(".,;:")
            company_key, product_key = (
                _entity_key("company", company),
                _entity_key("product", product),
            )
            event_key = _entity_key("event", match.group(0))
            entities.setdefault(
                company_key,
                EntityProposal(
                    company_key,
                    NodeType.COMPANY,
                    company,
                    match.start("company"),
                    match.end("company"),
                    confidence=0.9,
                ),
            )
            entities[product_key] = EntityProposal(
                product_key,
                NodeType.PRODUCT,
                product,
                match.start("product"),
                match.end("product"),
                confidence=0.92,
            )
            entities[event_key] = EntityProposal(
                event_key,
                NodeType.EVENT,
                event_name,
                match.start(),
                match.start() + len(event_name),
                confidence=0.96,
                attributes={
                    "subtype": "product_launch",
                    "verb": match.group("verb").casefold(),
                    "occurred_at": (
                        evidence.published_at.isoformat() if evidence.published_at else None
                    ),
                    "time_basis": "source_publication_time",
                },
            )
            relationships.extend(
                (
                    RelationshipProposal(
                        EdgeType.BUILDS,
                        company_key,
                        product_key,
                        match.start(),
                        match.end(),
                        0.92,
                        {"basis": "explicit_launch"},
                    ),
                    RelationshipProposal(
                        EdgeType.PARTICIPATED_IN,
                        company_key,
                        event_key,
                        match.start(),
                        match.end(),
                        0.96,
                        {"role": "actor"},
                    ),
                    RelationshipProposal(
                        EdgeType.PARTICIPATED_IN,
                        product_key,
                        event_key,
                        match.start(),
                        match.end(),
                        0.96,
                        {"role": "object"},
                    ),
                )
            )

        for index, sentence_match in enumerate(_SENTENCE.finditer(text)):
            raw = sentence_match.group(0)
            sentence = raw.strip()
            if not sentence or _BOILERPLATE.search(sentence):
                continue
            left_trim = len(raw) - len(raw.lstrip())
            start = sentence_match.start() + left_trim
            end = start + len(sentence)
            belief_start, proposition = self._belief_text(sentence, start)
            if proposition is None:
                if len(sentence.split()) >= 8 and not _EVENT_ONLY.search(sentence):
                    ambiguous.append((start, end))
                continue
            key = f"belief:{index}:{sha256(proposition.casefold().encode()).hexdigest()[:12]}"
            stance = self._stance(proposition)
            modality = self._modality(proposition)
            horizon = self._horizon(proposition)
            scope = self._scope(proposition)
            beliefs.append(
                BeliefProposal(
                    key,
                    proposition,
                    belief_start,
                    belief_start + len(proposition),
                    stance,
                    modality,
                    scope,
                    horizon,
                    0.86,
                )
            )
            relationships.append(
                RelationshipProposal(
                    EdgeType.EXPRESSES,
                    "content",
                    key,
                    belief_start,
                    belief_start + len(proposition),
                    0.9,
                    {"stance": stance, "modality": modality},
                )
            )
            if author_key and _FIRST_PERSON.search(sentence) and attribution(sentence) == "first_person":
                relationships.append(
                    RelationshipProposal(
                        EdgeType.BELIEVES,
                        author_key,
                        key,
                        belief_start,
                        belief_start + len(proposition),
                        0.91,
                        {"basis": "explicit_first_person"},
                    )
                )

        return ExtractionResult(
            tuple(entities.values()),
            tuple(beliefs),
            tuple(relationships),
            ambiguous_spans=tuple(ambiguous),
        )

    def extract_metadata(self, evidence: Evidence) -> ExtractionResult:
        text = evidence.normalized_text or evidence.raw_text
        entities: dict[str, EntityProposal] = {}
        relationships: list[RelationshipProposal] = []
        content = EntityProposal(
            key="content",
            node_type=NodeType.CONTENT,
            name=evidence.original_reference[:500],
            start=0,
            end=max(1, min(len(text), len(evidence.original_reference))),
            external_ids=(
                ExternalIdentifierProposal(
                    f"content:{evidence.source_type}", evidence.external_id or evidence.content_hash
                ),
            ),
            attributes={
                "source_type": evidence.source_type,
                "source_url": str(evidence.source_url),
                "document_version_id": str(evidence.document_version_id or ""),
                "published_at": evidence.published_at.isoformat()
                if evidence.published_at
                else None,
            },
        )
        entities[content.key] = content
        author_key = self._metadata_author(evidence, text, entities)
        if author_key:
            relationships.append(
                RelationshipProposal(
                    EdgeType.PUBLISHED,
                    author_key,
                    "content",
                    0,
                    max(1, len(text)),
                    0.99,
                    {"basis": "source_author_metadata"},
                )
            )
        return ExtractionResult(tuple(entities.values()), relationships=tuple(relationships))

    def _metadata_author(
        self, evidence: Evidence, text: str, entities: dict[str, EntityProposal]
    ) -> str | None:
        metadata: dict[str, Any] = evidence.metadata
        handle = str(metadata.get("author_handle") or metadata.get("author") or "").strip()
        did = str(metadata.get("did") or "").strip()
        resource = metadata.get("openalex_resource")
        openalex_id = str(metadata.get("openalex_id") or "").strip()
        name = evidence.original_reference.strip()[:500]
        if resource == "authors" and openalex_id:
            key = "metadata_author"
            entities[key] = EntityProposal(
                key,
                NodeType.PERSON,
                name,
                0,
                max(1, len(name)),
                external_ids=(ExternalIdentifierProposal("openalex_author", openalex_id),),
                confidence=1.0,
            )
            return key
        if resource == "institutions" and openalex_id:
            key = "metadata_institution"
            entities[key] = EntityProposal(
                key,
                NodeType.COMPANY,
                name,
                0,
                max(1, len(name)),
                external_ids=(ExternalIdentifierProposal("openalex_institution", openalex_id),),
                confidence=1.0,
            )
            return key
        if not handle and not did:
            return None
        canonical = handle.removeprefix("@") or did
        identifiers = []
        github_id = metadata.get("author_github_id")
        if evidence.source_type == "github" and github_id:
            identifiers.append(ExternalIdentifierProposal("github_user_id", str(github_id)))
        if did:
            identifiers.append(ExternalIdentifierProposal("bluesky_did", did))
        if handle and not (evidence.source_type == "github" and github_id):
            identifier_type = (
                "bluesky_handle"
                if evidence.source_type == "bluesky"
                else f"{evidence.source_type}_user"
            )
            identifiers.append(
                ExternalIdentifierProposal(identifier_type, handle.removeprefix("@"))
            )
        key = "metadata_author"
        entities[key] = EntityProposal(
            key,
            NodeType.PERSON,
            canonical,
            0,
            max(1, min(len(text), len(canonical))),
            aliases=(handle, f"@{handle.removeprefix('@')}") if handle else (),
            external_ids=tuple(identifiers),
            confidence=1.0,
        )
        return key

    @staticmethod
    def _belief_text(sentence: str, absolute_start: int) -> tuple[int, str | None]:
        if (
            sentence.endswith("?")
            or len(sentence.split()) < 5
            or not _PROPOSITION.search(sentence)
            or not _RELEVANCE.search(sentence)
            or _NON_CLAIM.search(sentence)
            or sentence[0].islower()
            or sentence[0].isdigit()
            or "http" in sentence.casefold()
            or "](" in sentence
            or sentence.startswith("#")
        ):
            return absolute_start, None
        attribution = _ATTRIBUTION.match(sentence)
        if attribution:
            sentence = sentence[attribution.end() :]
            absolute_start += attribution.end()
        else:
            attribution = _ATTRIBUTION_ANYWHERE.search(sentence)
            if attribution:
                sentence = sentence[attribution.end() :]
                absolute_start += attribution.end()
        sentence = sentence.strip()
        if not sentence or (
            _EVENT_ONLY.search(sentence)
            and not re.search(r"\b(will|should|because)\b", sentence, re.I)
        ):
            return absolute_start, None
        if len(sentence.rstrip(". ")) > 500:
            return absolute_start, None
        return absolute_start, sentence.rstrip(". ")

    @staticmethod
    def _stance(text: str) -> str:
        lowered = text.casefold()
        if re.search(r"\b(not|never|won't|cannot|unlikely)\b", lowered):
            return "opposes"
        if re.search(r"\b(many|some|only|unless|when|for certain|in some)\b", lowered):
            return "qualifies"
        return "supports"

    @staticmethod
    def _modality(text: str) -> str:
        lowered = text.casefold()
        if re.search(r"\b(should|must)\b", lowered):
            return "normative"
        if "because" in lowered or re.search(r"\b(causes?|drives?|leads? to)\b", lowered):
            return "causal-claim"
        if re.search(r"\b(will|would|likely|may|might|could)\b", lowered):
            return "predicted"
        return "observed"

    @staticmethod
    def _horizon(text: str) -> str:
        years = re.findall(r"\b20\d{2}\b", text)
        if years:
            return "–".join((years[0], years[-1])) if len(years) > 1 else years[0]
        return "current"

    @staticmethod
    def _scope(text: str) -> str:
        lowered = text.casefold()
        for phrase in (
            "enterprise workloads",
            "enterprise inference",
            "consumer applications",
            "edge devices",
            "ai infrastructure",
            "language models",
        ):
            if phrase in lowered:
                return phrase
        return "unspecified"
