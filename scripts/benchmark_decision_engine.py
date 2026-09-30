"""Legacy decision fixtures: local label agreement, never a provider comparison."""
import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import time
from memesis.reasoning.decision_engine import (
    DecisionType, FrontierLLMDecisionEngine, HeuristicDecisionEngine, TypeSafeJevDecisionEngine,
)
from memesis.quality.service import write_new, fingerprint


def run_benchmark(output=None, allow_live_jev=False):
    dataset_path = Path(__file__).resolve().parents[1] / "data/eval/gold_decisions.json"
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    jev = TypeSafeJevDecisionEngine()
    if not allow_live_jev:
        jev.api_key = None
        jev.openrouter_api_key = None
    engines = {
        "heuristic": HeuristicDecisionEngine(),
        "jev_live_attempts" if allow_live_jev else "jev_offline_simulation": jev,
        "frontier_offline_simulation": FrontierLLMDecisionEngine(),
    }
    traces, summaries = {}, {}
    for name, engine in engines.items():
        rows = []
        for case in cases:
            start = time.perf_counter()
            try:
                result = engine.evaluate(DecisionType(case["decision_type"]), case["context"], case["allowed_outputs"])
                rows.append({
                    "case_id": case["id"], "expected_draft_label": case["expected"],
                    "agrees_with_draft_label": result.decision == case["expected"],
                    "result": result.model_dump(mode="json"),
                    "measured_runner_elapsed_ms": (time.perf_counter() - start) * 1000,
                    "error": None,
                })
            except Exception as error:
                rows.append({
                    "case_id": case["id"], "agrees_with_draft_label": False,
                    "result": None, "measured_runner_elapsed_ms": (time.perf_counter() - start) * 1000,
                    "error": type(error).__name__,
                })
        traces[name] = rows
        summaries[name] = {
            "draft_label_agreement_count": sum(r["agrees_with_draft_label"] for r in rows),
            "case_count": len(rows), "error_count": sum(r["error"] is not None for r in rows),
            "execution_modes": dict(Counter(
                r["result"]["metadata"].get("execution_mode", "heuristic") if r["result"] else "failed" for r in rows)),
            "semantic_accuracy_validated": False, "billed_cost": None,
        }
    report = {
        "status": "fixture_diagnostics_only", "created_at": datetime.now(UTC).isoformat(),
        "dataset_hash": fingerprint(cases), "live_jev_explicitly_allowed": allow_live_jev,
        "provider_comparison_valid": False, "selection_policy_supported": False,
        "quality_winner": None, "cost_savings_claim": None, "summaries": summaries, "traces": traces,
        "limitations": [
            "Reference labels have no verified independent human review in this runner.",
            "Offline Jev and frontier reuse local rules, not independent model executions.",
            "Runner elapsed time is not paired provider inference latency.",
            "Use quality-compare for paired live receipts and human review for semantic quality.",
        ],
    }
    if output is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        output = Path("artifacts/intelligence-evaluation") / ("legacy-decisions-" + stamp + ".json")
    write_new(output, report)
    print(json.dumps({"output": str(output), "provider_comparison_valid": False, "summaries": summaries}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-live-jev", action="store_true", help="Explicitly allow configured Jev requests; frontier remains simulated")
    args = parser.parse_args()
    run_benchmark(args.output, args.allow_live_jev)
