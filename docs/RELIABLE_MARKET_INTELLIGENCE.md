# Reliable connected market intelligence

This change extends the merged evidence-memory build. It does not establish prediction accuracy or customer validation.

## Semantic processing

- Query words replace the former AI vocabulary boosts. Explicit market boundaries and supported paths remain; ambiguous relevance cannot silently disprove a connection. Opposing/qualifying relations receive a retrieval boost within the existing finite budgets.
- Perception rules preserve exact spans, all named subjects, attribution, negation and conditions as candidates in the assertion ledger. They do not assign a confident sentiment, guess an actor from document order or automatically create PERCEIVES edges. Existing perceptions are labelled proposed legacy output when used in answers.
- Extractor version is `deterministic-market-neutral-v7`. Rebuild preserved sources with `memesis rebuild-memory`; it protects raw history, prior rejection and human reviews. Old unowned perception edges remain historical legacy assertions, not automatically validated sentiment. A controlled rebuild is required to populate new candidates in an existing database.
- Historical comparisons require accepted memory observations: set `context.historical_case` on the earlier observation, retain a publication date and exact cited spans, and provide a shared explicit `context.use_case` or a shared relation with the same resolved subject. Both sides must be inside the query scope and backed by different source records. Missing history returns no analogy and an explicit gap; no match probability is invented. Human review is not causal validation.

## Repeated webpage collection

Watch sources now accept `web` with `page_url`. Each scheduled scan renders the configured page with browser cache bypassed. Checkpoints describe fetched content, not a permanent URL completion. Ledger hashes suppress repeat extraction; changed content retains document versions. Existing URL-hash checkpoints are compatible and no longer suppress revisits. Robots rules apply to the actual path. Only configured URLs are checked; this is not a site crawler.

## Provider accounting and reporting

The TypeSafe request uses `state`, typed `questions` and returned `answers`, according to the current [HTTP API](https://docs.typesafe.ai/api). Provider decisions must satisfy the named output contract. Low confidence cannot escalate to a simulated frontier model. Local fallbacks remain explicitly identified.

Each query counts newly attempted decision, strategic reasoning and support-check calls, including malformed responses and failed calls with unknown billing. Cache hits and local rules add no provider tokens. Token totals are provider-reported subtotals, marked incomplete when usage is missing. Configure per-model tier input/output prices through the four `MEMESIS_*_USD_PER_MILLION` fields; otherwise cost is unavailable. Configured prices are estimates, not invoices. A tier assumes the deployed models use its configured price; use separate configurations if they differ.

The static reports were withdrawn. `scripts/generate_all_reports.py` renders actual answers, citations, gaps and execution metrics and explicitly marks the baseline/comparison unavailable. No savings or quality winner is asserted.

## Interface

Open **Investigations & review** in the market workspace. Create or edit a watchlist, choose sources and graph/date boundaries, pause/resume a schedule, queue a run, inspect worker health and source lag, browse saved snapshots and processing receipts, and review patterns or memory observations. Review forms require a reviewer name, note and source-inspection acknowledgement. Reviews retain their history; pattern reviews do not approve graph facts. Memory reviews queue affected investigations for re-analysis.

The frontend shows current-market observations by default, with an explicit all-market option. Collection-only watches use configured search results and bounded connected paths; no market is auto-assigned. No-source, no-market watches explicitly use existing global memory. The API/preview still does not start the worker.

## Run and review across markets

1. `memesis quality-run --dataset data/evaluation/cross_market_quality_v1.json --output-dir artifacts/intelligence-evaluation/<new-name>` creates isolated battery, agriculture, industrial-heat, forecast-gap and deliberately empty-memory traces. These are synthetic diagnostic exercises, not live market findings.
2. `python scripts/prepare_market_review.py --output-dir artifacts/intelligence-evaluation/<new-live-name> --collect` creates a separate SQLite review workspace and performs one bounded public-source scan for each non-AI question. No extraction/reasoning provider calls are allowed during this preparation. Source failures and incomplete pagination remain visible. The resulting watchlists are paused and need a worker for continued scans.
3. Inspect source passages, alternatives, counterevidence and missing information. A person fills `reviews.json`; no assistant-generated quality pass or customer outcome is recorded. Use `quality-score` for the trace-bound diagnostic reviews.
4. To use the live review workspace in the interface, run the API/worker with `MEMESIS_DATABASE_URL=sqlite:///<absolute-path-to-review.sqlite3>`. Keep the preview database separate. Configure models explicitly if live strategic interpretation is wanted.

The local prototype still uses caller-supplied reviewer names. Authenticated reviewer identity and deployment access control remain separate production work.
