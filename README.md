# Memesis

Memesis stores source evidence, canonical entities, belief claims, and a typed temporal graph with provenance attached to every derived record.

## Phase 2 evidence ingestion

Requires Python 3.12+. Dependencies are locked in `uv.lock`.

```sh
uv sync --locked --extra dev
cp .env.example .env
uv run memesis db-upgrade
uv run memesis health
uv run uvicorn memesis.app:app --reload
uv run pytest
```

The configured database is PostgreSQL. For an isolated local demo or test, explicitly select SQLite:

```sh
uv run memesis demo --database-url sqlite:///./memesis-demo.sqlite3
```

Run the bounded, no-LLM evidence collector with an explicit database URL:

```sh
uv run memesis --database-url sqlite:///./memesis-ingest.sqlite3 ingest \
  --query "AI infrastructure" --limit 2
```

The command collects one policy-gated Crawl4AI web page, Hacker News, Bluesky
AppView (with a Jetstream-compatible envelope), OpenAlex authors/works/topics/
institutions, and one RSS feed. It persists immutable raw versions, normalizes
and content-hash deduplicates them, then reports normalized evidence emitted,
checkpoints, API requests, cache hits, storage counts, and zero LLM calls.
Install the Crawl4AI browser runtime once before using the web adapter:

```sh
uv run playwright install chromium
```

The demo creates source-backed Person, Belief, and Content nodes, adds `PUBLISHED` and `EXPRESSES` edges, retrieves a two-hop subgraph, and prints its provenance.

The graph storage boundary is `GraphRepository`; its current SQL implementation uses adjacency tables and a recursive query. Memesis business and CLI code uses this interface rather than Graphiti APIs. Graphiti is retained as a temporal/provenance design reference per `docs/DEPENDENCY_AUDIT.md`.

The package boundaries are `sources`, `ingestion`, `evidence`, `knowledge`, `graph`, `retrieval`, and `reasoning`. Collection remains separate from graph projection, and model-driven reasoning remains inactive.

## Phase 3 Evidence → Graph

Apply migrations, project normalized evidence, and run the frozen evaluation:

```sh
uv run memesis db-upgrade
uv run memesis build-graph
uv run memesis evaluate-phase3
```

`build-graph` performs deterministic metadata/entity/time/proposition extraction first,
creates exact evidence spans and validated assertions, resolves only stable identifiers or
structurally equivalent beliefs, and writes provenance-backed graph edges. Extraction is
cached by content hash, ontology, schema, extractor, prompt, and configured model versions.

Cheap and ambiguity-model integrations implement the provider-neutral
`StructuredExtractionModel` protocol. Only unresolved span packs are sent to a model;
packs are capped at 6,000 characters, and every model result must provide its model name,
prompt version, token counts, confidence, and original evidence offsets. No provider or
model is required for deterministic processing.

To enable the optional fallback, configure `MEMESIS_MODEL_API_KEY` and
`MEMESIS_EXTRACT_SMALL_MODEL` for an OpenAI-compatible endpoint. A configured
`MEMESIS_REASON_STRONG_MODEL` receives only spans the cheap model explicitly leaves
ambiguous. Model output that lacks exact source offsets, valid graph endpoints, or literal
supporting text is rejected before it can create graph records.

## Reasoning evidence audit

Market and date boundaries are shared by workspace reads, reasoning retrieval and
score computation. See [Market and date scope](docs/MARKET_SCOPING.md) for API/CLI
parameters, adjacent-market exploration and historical-cutoff semantics.

Reasoning answers keep claims linked to packet evidence. A resolvable citation means
the source record is available; it does not by itself prove that the source supports
the claim. The API and CLI expose citation-link status, source text and timestamps,
and an audit record. Historical analogy matches are heuristic and their curated
historical templates are explicitly marked as unsourced.

An optional advisory support check can assess cited observed and inferred claims:
set `MEMESIS_VERIFY_CLAIM_SUPPORT=true`, `MEMESIS_MODEL_API_KEY`, and
`MEMESIS_REASON_STRONG_MODEL`. The configured OpenAI-compatible model receives only
the cited source excerpts and returns a support annotation. Speculative claims stay
in the answer as exploratory hypotheses; unsupported, unresolved, or unverified
claims are never removed or rewritten by this check. The model judgment is not a
truth score and should be reviewed before relying on it.

The 30-example fixture is at
`data/evaluation/phase3_examples.json`. It includes topics that must not become beliefs,
falsifiable propositions, stable-identifier alias resolution, same-name non-merges,
events, relationships, boilerplate, questions, and model-token accounting.

## Deterministic scoring layer

Compute the six v0 graph/time-series scores at an explicit historical cutoff:

```sh
uv run memesis db-upgrade
uv run memesis compute-scores \
  --as-of 2026-09-29T00:00:00+00:00 --window-days 30
uv run memesis explain-score --score-id <uuid>
```

The layer computes Actor Lead, Actor Influence, Belief Velocity, Belief Diversity,
Action Conversion, and Evidence Confidence. It invokes no model and never uses an
extractor's declared confidence as a scoring input. Every persisted record contains its
formula/version, historical cutoff, component values and weights, raw numerators and
denominators, coverage gaps, evidence IDs, and a content fingerprint. Repeating a frozen
calculation is idempotent. See [the scoring specification](docs/PHASE4_DETERMINISTIC_SCORES.md)
for the exact v0 formulas and limitations.

`GET /healthz` is the only HTTP route in this phase. No collection adapters or autonomous workflows are active.
