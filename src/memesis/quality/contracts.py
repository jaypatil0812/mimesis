from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

LAYERS = ("collection", "extraction", "resolution", "retrieval", "reasoning")
RUBRIC = ("traceability", "counterevidence", "alternatives", "uncertainty", "next_decision_step")


class DocumentCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str = Field(min_length=1)
    source_type: str = "fixture"
    source_url: str | None = None
    published_at: str = "2026-09-20T00:00:00+00:00"
    known_at: str = "2026-09-21T00:00:00+00:00"
    metadata: dict = Field(default_factory=dict)
    captured: bool = True


class QualityCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    tags: list[str]
    origin: Literal["synthetic_adversarial", "public_document", "user_supplied", "customer_supplied"]
    question: str
    decision: str
    expected_answer_kind: Literal["disagreement", "insufficient_evidence", "unexpected_explanation", "qualified_support"]
    assessment_notes: list[str]
    documents: list[DocumentCase] = Field(min_length=1)
    expected_beliefs: list[str] | None = None
    required_documents: list[str] = Field(default_factory=list)
    author_pairs: list[dict] = Field(default_factory=list)
    gold_review_status: Literal["draft", "human_approved"] = "draft"
    gold_reviewer: str | None = None
    customer_confirmed: bool = False

    @model_validator(mode="after")
    def valid_case(self):
        ids = [d.id for d in self.documents]
        if len(ids) != len(set(ids)) or not set(self.required_documents) <= set(ids):
            raise ValueError("Unique documents and valid required-document references are required")
        if self.gold_review_status == "human_approved" and not self.gold_reviewer:
            raise ValueError("Approved gold requires a named human reviewer")
        for pair in self.author_pairs:
            if pair.get("left") not in ids or pair.get("right") not in ids or not isinstance(pair.get("same"), bool):
                raise ValueError("Invalid author pair")
        return self


class QualitySuite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    cases: list[QualityCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case IDs")
        return self


class CaseReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    trace_hash: str
    gold_approved: bool = False
    reviewer: str | None = None
    reviewer_role: Literal["human", "assistant", "pending"] = "pending"
    layer_verdicts: dict[str, Literal["pass", "fail", "not_evaluated", "pending"]]
    findings: dict[str, str]
    usefulness: dict[str, Annotated[int, Field(strict=True, ge=0, le=2)] | None]
    decision_effect: Literal["changes_decision", "clarifies_next_step", "not_useful", "pending"] = "pending"
    decision_before: str = ""
    decision_after: str = ""
    customer_confirmed: bool = False

    @model_validator(mode="after")
    def complete_review(self):
        if set(self.layer_verdicts) != set(LAYERS) or set(self.findings) != set(LAYERS):
            raise ValueError("Each layer needs a separate verdict and finding")
        if set(self.usefulness) != set(RUBRIC):
            raise ValueError("All five usefulness criteria are required")
        if any(v is not None and (isinstance(v, bool) or not 0 <= v <= 2) for v in self.usefulness.values()):
            raise ValueError("Usefulness ratings must be 0, 1, 2 or null")
        if self.gold_approved:
            if self.reviewer_role != "human" or not self.reviewer or not self.reviewer.strip():
                raise ValueError("Only an explicit named human review can approve gold")
            if "pending" in self.layer_verdicts.values() or any(not s.strip() for s in self.findings.values()):
                raise ValueError("Approval requires findings for all layers, including limitations")
        if self.decision_effect != "pending":
            if not self.gold_approved or not self.decision_before.strip() or not self.decision_after.strip():
                raise ValueError("A decision-effect rating requires approved review and before/after decisions")
            if any(v is None for v in self.usefulness.values()):
                raise ValueError("A decision-effect rating requires all usefulness ratings")
        return self
