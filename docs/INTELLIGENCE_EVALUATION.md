# Intelligence quality and decision usefulness

This evaluation separates five layers instead of reporting a single accuracy
score. It distinguishes draft automated diagnostics, human semantic review,
real-source coverage and customer decision outcomes.

## Run alongside development

```powershell
.venv\Scripts\python.exe -m memesis.cli quality-run --output-dir artifacts/intelligence-evaluation/my-run
.venv\Scripts\python.exe -m memesis.cli --database-url sqlite:///./memesis-phase5.sqlite3 quality-sample --output-dir artifacts/intelligence-evaluation/my-live-review --limit 24 --investigate-question --question "What's the next big thing?"
.venv\Scripts\python.exe -m memesis.cli quality-score --report artifacts/intelligence-evaluation/my-run/report.json --reviews artifacts/intelligence-evaluation/my-run/reviews.json --output artifacts/intelligence-evaluation/my-run/score.json
```

Use a new output directory for each run. Existing report files cannot be
overwritten through these commands. Reports retain dataset, code and trace
hashes; reviews are rejected when the executed report changes. Review packets
are ignored by Git because they may contain source or customer information.
The regression tests also exercise the adversarial suite on ordinary test runs.

`quality-run` uses a fresh isolated SQLite database per case. It does not insert
benchmark fixtures into the preview database or change live market boundaries.
It is offline by default, even when credentials exist locally. Explicit
`--live-reasoning` permits configured strategic reasoning calls for these
synthetic cases; it requires a key/model and can incur provider costs.
Deterministic extraction is the default evaluated extractor, not a claim about
the quality of a separately configured extraction model.

`quality-sample` reads preserved public evidence and recent investigation
snapshots without collecting or projecting new facts. It samples up to 100
recent records per source, prioritizes difficulty cues and draws across sources.
Full normalized text, dates, stable IDs, metadata and document-version pointers
remain in the JSON. Cues do not establish negation, criticism or contradiction.
This is a review queue, not a random or representative sample. Its live question
pass uses bounded paths from sampled evidence; it cannot establish whole-market
coverage or predict the next major opportunity.

## Draft corpus

`data/evaluation/intelligence_quality_v1.json` contains 13 annotated cases:
negation, quoted criticism, multiple products, ambiguous same-name identities,
renamed handles, reposts, changing positions, contradictory evidence, sequence
without influence, battery chemistry, logistics downtime, a deliberately missing
utility report, and the user's question **"What's the next big thing?"**.

Reference annotations are authored drafts, not human-approved gold. Disagreement,
insufficient evidence and unexpected explanations are explicitly valid outcomes.
The non-AI cases expose domain vocabulary bias. Improving a formatting mismatch
must not be reported as improved semantic intelligence.

## What is measured

| Layer | Automated diagnostic | Human review |
| --- | --- | --- |
| Collection | Known fixture manifest present/absent; durable deduplicated documents count as captured | Compare actual source snapshots, queries, pagination, time windows and missing records; report unknown recall |
| Extraction | Exact proposition matching, ignoring whitespace and a final period; projection validation failures | Review exact spans, speaker/quotation, negation, conditions, products and observation meaning; record both omissions and invented claims |
| Resolution | Explicit numeric author identity pairs | Verify people/company/product identity using corroborated identifiers; audit candidate merges |
| Retrieval | Required available evidence retained, including opposing records | Inspect missing relevant/counterevidence and graph paths; separate upstream collection gaps from retrieval failures |
| Reasoning | Schema/path/reference validity and provider execution status | Judge semantic support, alternatives, omitted premises, scope and overclaims; valid citations do not prove entailment |

The deliberately missing utility report measures a known manifest gap. It does
not measure Hacker News/GitHub recall. Resolution diagnostics cover the specified
author pairs, not every graph entity. Exact text matching is not a semantic judge.
Unconfigured strategic reasoning is **not evaluated**, not passing and not zero
accuracy. A provider error is operational evidence, not an accuracy measurement.

## Human review and decision utility

Open `review.md`, inspect full `report.json`, then edit `reviews.json`. Each layer
needs its own verdict and finding with document/observation IDs and source spans.
Named human approval is required before reviews enter the quality summary.
Assistant annotations cannot self-approve. The CLI trusts the submitted reviewer
identity; it is not an authentication system or independent audit.

Rate five dimensions independently from 0 to 2: evidence traceability,
counterevidence, alternative explanations, calibrated uncertainty, and a useful
next decision step. Record `decision_before`, `decision_after`, and whether the
output changed a decision, clarified the next step, or was not useful.
Customer confirmation requires an actual customer exercise; a synthetic example
or the founder supplying a question does not establish customer usefulness.

Failure rates use only approved pass/fail verdicts for that layer. Not-evaluated
and unreviewed cases are visible and excluded from the denominator. No reviewed
cases produces null scores. Disagreement with the initial AI thesis is not a
failure. Preserve reference-label revisions and rerun with a new dataset hash
when human review corrects the gold; do not rewrite old traces.

## Provider comparisons

`FrontierLLMDecisionEngine` is explicitly an offline simulator. It makes no
frontier call. Its fabricated latency offset, token counts, cost and confidence
boost are removed. Offline Jev results likewise carry simulation metadata and
no invented provider usage/cost. Local computation time is not model inference
latency. Actual TypeSafe/OpenRouter attempts carry request/response hashes;
price projections remain marked as assumptions rather than billed costs.

Decision cache keys now include engine identity and output contract. Cache hits
are flagged and cannot qualify as live provider latency observations. Older
Phase 5 evaluation is explicitly an execution/retrieval regression, not a
Jev-versus-frontier or intelligence-quality benchmark.

```powershell
.venv\Scripts\python.exe -m memesis.cli quality-compare --traces paired-provider-traces.json --output comparison.json
```

Submitted pairs must match task, input hash, evidence references and output
contract, and carry successful live request/response receipts. Simulations,
fallbacks, cache hits and unpaired inputs are excluded. Provider-reported usage
and billing are separate availability flags; estimates cannot become billed
savings. Eligible receipts still require human provenance/quality review and
matched-condition repetitions. The tool does not declare a winner from latency.
The frontier simulator remains ineligible until a real adapter is implemented
and measured. Receipts are structured evidence, not cryptographic proof that a
caller told the truth.

For a real comparison, freeze the human-approved held-out cases, use identical
inputs and contracts, disable caches, alternate provider order, retain failures,
measure repeated latency distributions, record actual usage/cost and grade
answers blind. Keep prompt-development examples separate from held-out examples.
Do not tune to the holdout and then present it as an independent evaluation.
