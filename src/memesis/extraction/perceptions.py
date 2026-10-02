"""Span-backed perception candidates; sentiment and attribution require review."""
import re
from memesis.domain.schemas import NodeType
from memesis.extraction.contracts import ObservationProposal
from memesis.extraction.meaning import attribution, meaning

PERCEPTION_VERSION = "perception-candidates-v1"
DIMENSIONS = {
    "PRICE_SENSITIVITY": r"\b(costs?|prices?|expensive|cheap|bill|budget)\b",
    "PERFORMANCE": r"\b(latency|slow|fast|throughput|yield|efficiency|capacity|durability)\b",
    "PAIN": r"\b(broken|frustrating|crash|outage|unreliable|failure|failed)\b",
    "SWITCHING_INTENT": r"\b(switched|migrated|replaced|leaving)\b",
    "FEATURE_REQUEST": r"\b(wish|need|missing feature|please add)\b",
    "USABILITY": r"\b(easy to use|difficult to setup|setup|usability)\b",
    "TRUST": r"\b(privacy|security|trust|audit|leak)\b",
    "PRAISE": r"\b(love|amazing|impressed)\b",
}


def candidates(text, resolved):
    targets = {node.id: node for node in resolved.values()
               if getattr(node, "node_type", None) in {NodeType.PRODUCT, NodeType.COMPANY, NodeType.MARKET}}
    author = resolved.get("metadata_author")
    for match in re.finditer(r"[^\n.!?]+(?:[.!?]+|$)", text):
        statement = match.group().strip()
        start = match.start() + len(match.group()) - len(match.group().lstrip())
        dimensions = [key for key, pattern in DIMENSIONS.items() if re.search(pattern, statement, re.I)]
        mentioned = [node for node in targets.values() if any(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", statement, re.I)
                     for name in [node.name, *node.attributes.get("aliases", [])] if name)]
        if not dimensions or not mentioned:
            continue
        mode = attribution(statement)
        own_experience = mode == "first_person" and getattr(author, "node_type", None) == NodeType.PERSON
        for subject in mentioned:
            context = {"classification_basis": PERCEPTION_VERSION, "requires_semantic_review": True,
                "perception_dimensions": dimensions, "stance": "neutral", "sentiment_status": "unresolved",
                "meaning": meaning(statement), "mentioned_subject_ids": [str(n.id) for n in mentioned],
                "multiple_subjects_require_disambiguation": len(mentioned) > 1,
                "source_statement": statement, "source_start": start, "source_end": start + len(statement)}
            if own_experience:
                context["actor_id"] = str(author.id)
                context["attribution_basis"] = "source_metadata_account_and_first_person_candidate"
            yield ObservationProposal("customer_experience" if own_experience else "attributed_claim",
                start, start + len(statement), subject_key="perception_subject", statement=statement,
                attribution=mode, confidence=0.5, context=context), subject
