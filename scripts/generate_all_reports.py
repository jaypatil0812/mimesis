"""Render evidence-dependent reports; do not manufacture a frontier baseline."""
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from memesis.config import settings
from memesis.db.session import make_engine, make_session_factory
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.reasoning.engine import MemesisReasoningEngine
from memesis.retrieval.scope import QueryScope
from uuid import UUID


def generate(question="What changed in the recorded market evidence?", market_id=None, output_dir="reports"):
    engine = make_engine(settings.database_url)
    try:
        repo = SqlGraphRepository(make_session_factory(engine))
        answer, metrics, packet = MemesisReasoningEngine(repo).answer_query(question,
            scope=QueryScope(market_id=UUID(market_id) if market_id else None))
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        lines = ["# Evidence report", "", "Generated: " + datetime.now(UTC).isoformat(),
            "Question: " + question, "", "## Answer", "", answer.summary,
            "", "Reasoning status: " + str(answer.reasoning_execution.get("status", "not_configured")),
            "", "## Trace", ""]
        for section in ("what_is_happening", "who_matters", "what_they_believe", "company_actions", "perception", "what_changed", "adjacent_markets", "possible_implications", "contradictory_evidence"):
            claims = getattr(answer, section)
            if claims:
                lines.extend(["### " + section.replace("_", " "), ""])
            for claim in claims:
                lines.extend(["- [" + claim.epistemic_status.value + "] " + claim.text,
                    "  Evidence: " + ", ".join(claim.evidence_ids), "  Reasoning: " + (claim.reasoning or "Not supplied")])
        lines.extend(["", "## Coverage gaps", "", *["- " + gap for gap in answer.unknown_or_missing],
            "", "## Usage", "", "```json", json.dumps(metrics.model_dump(mode="json"), indent=2), "```",
            "", metrics.cost_semantics, "", "## Sources", ""])
        lines.extend("- " + e["id"] + ": " + str(e["source_url"]) for e in packet.primary_evidence_references)
        (directory / "MIMESIS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (directory / "BASELINE.md").write_text("# Baseline unavailable\n\nNo paired live frontier execution was measured by this script.\n", encoding="utf-8")
        (directory / "COMPARISON.md").write_text("# Comparison unavailable\n\nNo measured Jev-versus-frontier quality, savings or speed advantage is established. Use trace-bound live pairs and human review.\n", encoding="utf-8")
        (directory / "execution.json").write_text(json.dumps({"answer": answer.model_dump(mode="json"), "metrics": metrics.model_dump(mode="json"), "packet_hash": packet.packet_hash, "query_scope": packet.query_scope}, indent=2), encoding="utf-8")
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default="What changed in the recorded market evidence?")
    parser.add_argument("--market-id")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    generate(args.question, args.market_id, args.output_dir)
