"""Comparisons require reviewed, dated historical observations within query scope."""
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class HistoricalAnalogue(BaseModel):
    analogue: str
    similarities: list[str] = Field(min_length=1)
    differences: list[str] = Field(min_length=1)
    similarity_confidence: float | None = Field(default=None, ge=0, le=1)
    structural_matches: dict[str, Any] = Field(default_factory=dict)
    time_lag_observed: str | None = None
    current_evidence_ids: list[str] = Field(default_factory=list)
    historical_evidence_ids: list[str] = Field(default_factory=list)
    historical_basis_status: str = "reviewed_source_observation_not_causal_validation"


class HistoricalAnalogueEngine:
    def find_analogues(self, query, subgraph):
        evidence = {str(e.id): e for e in subgraph.evidence}
        observations = [o for o in subgraph.memory_observations if o.get("review_state") == "accepted"
            and o.get("published_at") and o.get("evidence_ids") and set(o["evidence_ids"]) <= evidence.keys()]
        historical = [o for o in observations if o.get("context", {}).get("historical_case")]
        current = [o for o in observations if not o.get("context", {}).get("historical_case")]
        matches = []
        for prior in historical:
            for now in current:
                if datetime.fromisoformat(prior["published_at"]) >= datetime.fromisoformat(now["published_at"]):
                    continue
                left, right = prior.get("context", {}), now.get("context", {})
                shared_use_case = left.get("use_case") and left.get("use_case") == right.get("use_case")
                shared_relation = (left.get("edge_type") and left.get("edge_type") == right.get("edge_type")
                    and prior.get("subject_id") == now.get("subject_id"))
                if not (shared_use_case or shared_relation):
                    continue
                if set(prior["evidence_ids"]) & set(now["evidence_ids"]):
                    continue
                matches.append(HistoricalAnalogue(analogue=str(left["historical_case"]),
                    similarities=["Reviewed sources share " + ("the explicit use case: " + str(left["use_case"]) if shared_use_case else "the relation and resolved subject: " + str(left["edge_type"]))],
                    differences=[f"Historical source ({prior['published_at']}): {prior['statement']}",
                        f"Current source ({now['published_at']}): {now['statement']}",
                        "Shared structure does not establish the same mechanism or outcome; no predictive match probability is measured."],
                    structural_matches={"historical_observation_id": prior["id"], "current_observation_id": now["id"]},
                    current_evidence_ids=now["evidence_ids"], historical_evidence_ids=prior["evidence_ids"]))
                break
            if len(matches) >= 3:
                break
        return matches
