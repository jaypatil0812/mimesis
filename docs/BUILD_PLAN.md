# Memesis Build Plan

Status: implementation sequence following architecture approval  
Scope: prove one question—“Is AI infrastructure shifting toward smaller/specialized models, and which actors and companies are driving that shift?”

> Owner-sequenced implementation note (2026-09-29): the requested “Phase 3:
> Evidence → Memesis Graph” combines the deterministic extraction and conservative
> resolution portions originally separated below as Phases 4 and 5. Its implemented
> boundary and evaluation are recorded in [PHASE3_EVIDENCE_GRAPH.md](./PHASE3_EVIDENCE_GRAPH.md).
> The six deterministic v0 scores are now implemented as the proprietary scoring layer;
> the later retrieval, reasoning, API, and UI phases remain unimplemented.

## Delivery rule

Each phase produces a reviewable artifact and an automated acceptance gate. A phase may change its internal implementation without changing the contracts accepted in earlier phases. Do not begin broad source acquisition until the gold evidence fixture, ontology rules, and source policies exist.

## Phase 0 — Freeze the proof contract

**Goal:** turn the research question into a falsifiable investigation and a reviewed test corpus.

Deliverables:

- investigation specification: proposition variants, time window, named markets, source families, inclusion/exclusion terms, and expected counterarguments;
- 30–50 manually reviewed source documents spanning company statements, research, product releases, Bluesky, Hacker News, GitHub, and counterevidence;
- exact evidence spans and expected entities, belief assertions, stance, events, edges, and intentional non-merges;
- source-policy entries for every fixture source;
- answer rubric covering provenance, balance, uncertainty, and decision usefulness.

Tests/gate:

- every expected conclusion traces to exact spans;
- at least 20% of the fixture is counterevidence or qualifying evidence;
- duplicate/syndicated content and ambiguous identities are represented;
- two reviewers agree on the meaning of the core belief set, or disagreements are explicitly encoded;
- no implementation dependency is needed to inspect the fixture.

**This is the first implementation task.** It provides the benchmark that prevents the team from optimizing ingestion volume while silently degrading meaning.

## Phase 1 — Evidence ledger and ontology constraints

**Status: foundation implemented and locally integration-tested on SQLite. PostgreSQL runtime verification remains open because no PostgreSQL server/container runtime was available in the implementation environment.**

**Goal:** establish the durable source/knowledge contracts in PostgreSQL.

Deliverables:

- [x] SQLAlchemy tables and initial Alembic migration for sources, versioned source policies, documents and immutable versions, normalized documents, evidence, evidence spans, assertions, graph nodes/edges, record revisions, merge decisions, and tombstones;
- [x] Pydantic canonical schemas for Person, Company, Belief, Market, Product, Content, Event, Source, Evidence, provenance, assertions, and evidence spans;
- [x] typed endpoint validation from [ONTOLOGY.md](./ONTOLOGY.md);
- [x] graph repository protocol with SQL implementation, create/read/update/soft-delete, evidence-backed edges, and recursive bounded subgraph retrieval;
- [x] package boundaries for source adapters, evidence, knowledge, graph, retrieval, and reasoning, with social adapters and model reasoning left inactive;
- [x] immutable source evidence plus prior graph-state snapshots on update and tombstones on delete;
- [x] environment-backed configuration, JSON logging, CLI health check, and HTTP `/healthz`;
- [x] demo evidence and CLI path to create a Person, Belief, Content, assert `EXPRESSES`, connect `PUBLISHED`, and retrieve the two-hop graph;
- [x] locked Python dependencies in `uv.lock` and test scaffolding.

Tests/gate:

- [x] SQLite-backed repository integration test persists and retrieves the complete Person → Content → Belief graph;
- [x] provenance round-trip verifies source URL/type, retrieval and publication times, original reference, raw evidence, confidence, and entity IDs;
- [x] migration integration test applies revision `0001_foundation` and checks the ledger tables;
- [x] PostgreSQL dialect DDL compilation succeeds without requiring a running server;
- [x] graph update snapshots the prior state; delete writes tombstones and removes records from active retrieval;
- [x] re-fetching an unchanged document hash is idempotent; changed content adds an immutable document version;
- [x] normalized text and exact evidence spans are content-addressed, immutable per normalizer version, and checked against stored offsets;
- [x] assertions and merge decisions require existing evidence spans and carry full provenance; assertion review transitions retain history and exclude superseded claims from the active set;
- [x] invalid ontology endpoints and missing extraction-model metadata fail validation;
- [x] developer CLI demo creates Person, Content, and Belief, writes `PUBLISHED` and `EXPRESSES`, retrieves two hops, and verifies the evidence round trip;
- [ ] run the same integration suite against PostgreSQL 17+ before treating the production database adapter as verified;

## Phase 2 — Deterministic ingestion core

**Goal:** collect and normalize approved sources without an LLM.

Deliverables:

- common adapter envelope;
- PostgreSQL job/lease/retry/dead-letter mechanism;
- HTTP/RSS collector with conditional requests and Trafilatura extraction;
- content hashing, canonical URL handling, exact dedupe, and simple near-duplicate/syndication detection;
- run metrics and source-budget enforcement.

Tests/gate:

- cursor advances only in the transaction that durably stores content;
- crash/retry yields one canonical version;
- unchanged ETag/hash performs no downstream work;
- robots/terms policy absence blocks a fetch;
- normalization snapshots are stable across repeated runs;
- deliberate duplicate and syndication fixtures are grouped correctly.

## Phase 3 — Structured source adapters

**Goal:** add only the structured sources needed for the proof.

Deliverables:

- OpenAlex API adapter with cursor pagination and field selection;
- GitHub organization/repository/release adapter;
- Hacker News Algolia adapter;
- Bluesky AppView historical seeding adapter;
- optional filtered Jetstream consumer after historical coverage is reviewed.

Tests/gate:

- recorded responses replay offline into identical normalized records;
- identifiers, timestamps, deletions, and pagination edge cases are covered;
- rate-limit and daily cost budgets halt gracefully;
- Jetstream reconnect/deduplication/tombstone tests pass before it runs continuously;
- fixture coverage shows each adapter adds distinct evidence, not merely volume.

## Phase 4 — Extraction and assertion validation

**Goal:** convert relevant spans into typed proposals once.

Deliverables:

- deterministic metadata, identifier, date, link, quote, and release parsers;
- relevance filter and stable span packer;
- provider-neutral model gateway with `extract_small` alias;
- versioned structured extraction schema for beliefs, stance, entities, events, and edges;
- exact-quote, endpoint, date, and evidence validators;
- cache keyed by content hash, span IDs, ontology, prompt, schema, and model version.

Tests/gate:

- zero invented citations on the gold fixture;
- every accepted assertion has a valid exact span;
- schema-invalid and ontology-invalid output is rejected, not repaired silently;
- repeated identical input causes no new paid call;
- extraction precision/recall is measured separately by object type and stance;
- cost and latency stay within [COST_MODEL.md](./COST_MODEL.md) limits.

## Phase 5 — Conservative entity and belief resolution

**Goal:** create canonical identities without destructive over-merging.

Deliverables:

- external-ID and alias indexes;
- deterministic candidate generation and transparent feature scoring;
- separate Person/Company/Product and Belief matching policies;
- review queue and reversible merge ledger;
- conflict and non-merge reason capture.

Tests/gate:

- exact identifiers resolve deterministically;
- ambiguous same-name people do not auto-merge;
- different belief scope/modality/horizon does not collapse;
- all reviewed merges can be reversed without loss;
- auto-merge precision target is at least 99% on the gold fixture; below that, thresholds become review-only.

## Phase 6 — Graph projection and scoring

**Status: deterministic v0 scoring implemented. Predictive calibration, market-specific
normalization, and outcome evaluation remain intentionally deferred.**

**Goal:** compute an inspectable market-specific graph and prioritization scores.

Deliverables:

- active graph projection from accepted assertions;
- source-independence clusters and publication sequence;
- [x] versioned actor lead/influence, belief velocity/diversity, action-conversion, and
  evidence-confidence scoring;
- [x] coverage field and full score decomposition;
- [x] historical-window computation without future leakage;
- [x] input fingerprints and idempotent score persistence;
- [ ] retrospective calibration against reviewed market outcomes.

Tests/gate:

- every edge returns its evidence and assertion history;
- identical/near-identical syndication does not count as independent amplification;
- scores are deterministic for a fixed ledger/version;
- time-window tests prevent later evidence from influencing earlier snapshots;
- removing one source family reveals score sensitivity rather than hiding it;
- no score is labeled truth, causality, or market prediction.

## Phase 7 — Retrieval and evidence packets

**Goal:** retrieve a small, balanced subgraph sufficient to answer the proof question.

Deliverables:

- lexical belief/content retrieval;
- bounded two-hop graph expansion;
- relevance, time, quality, and independence ranking;
- stance/source/organization diversity caps;
- counterevidence, conflict, and missing-source sections;
- reproducible packet manifest with a 12,000-token default ceiling.

Tests/gate:

- the gold evidence required by the answer rubric is present at acceptable recall;
- packet limits are never exceeded;
- one publisher or organization cannot dominate by repetition;
- excluded evidence and ranking reasons are inspectable;
- only if lexical-plus-graph recall misses the agreed target is a pgvector experiment authorized.

## Phase 8 — Reasoning and investigation API

**Goal:** produce a cited, uncertainty-aware answer without giving the model the corpus.

Deliverables:

- provider-neutral `reason_strong` call over the evidence packet;
- structured answer containing findings, actors, companies/actions, counterevidence, uncertainties, and next investigations;
- citation validator that accepts only packet evidence IDs;
- read/review API endpoints specified in [ARCHITECTURE.md](./ARCHITECTURE.md);
- complete run/token/cost lineage.

Tests/gate:

- every factual statement in the answer maps to one or more permitted evidence IDs;
- unsupported or over-causal claims fail validation or are clearly labeled hypotheses;
- adversarial packet tests expose conflicts and missing coverage;
- repeated run on a frozen packet is semantically stable enough for review;
- strong-model spend remains within the per-investigation cap.

## Phase 9 — Investigation UI and deployable proof

**Goal:** let a reviewer understand and challenge the answer.

Deliverables:

- answer-first page with evidence drawer;
- timeline and filtered Cytoscape graph;
- actor, belief, company-action, source-independence, and score-decomposition views;
- merge/assertion review workflow;
- local container composition and one small hosted deployment;
- backup, restore, health, and runbook documentation.

Tests/gate:

- a reviewer can move from conclusion to exact source span in at most two interactions;
- keyboard and screen-reader basics pass for all non-graph functionality;
- deletion/tombstone propagates through API and UI;
- restore test reproduces the investigation from database backup plus configuration;
- a fresh environment can run the proof with PostgreSQL and the application only.

## Phase 10 — Decide whether the thesis is proven

**Goal:** make an explicit product decision before broadening the platform.

Compare the Memesis answer with a manual analyst baseline on:

- source and actor coverage;
- provenance correctness;
- ability to distinguish origin, amplification, action, and outcome;
- handling of counterevidence and uncertainty;
- usefulness of company-specific next investigations;
- analyst time saved;
- cash and compute cost.

Proceed only if the system yields a materially more traceable and reusable investigation than search plus a prose summary. Otherwise revise the ontology/evidence method; do not compensate by adding more infrastructure.

## Deferred until a measured trigger

| Capability | Trigger |
|---|---|
| pgvector/embeddings | Lexical-plus-graph retrieval misses the agreed gold-fixture recall target |
| Browser automation | A necessary approved source cannot be collected by HTTP/feed/API and its value exceeds policy/ops cost |
| Separate object storage | Raw approved payloads exceed the PostgreSQL threshold or large binaries become necessary |
| Graph database | Indexed bounded SQL traversal misses latency targets at sustained graph scale |
| Redis or external queue | PostgreSQL leasing cannot meet measured throughput/latency/recovery needs |
| Kubernetes | Multiple independently scaling services and deployment environments actually exist |
| More social platforms | A documented evidence gap justifies their terms, cost, and moderation burden |
| Market-outcome prediction | Enough time-indexed outcomes exist for a leak-free retrospective validation |

## Definition of done for the vertical slice

The proof is complete when a reviewer can ask the target question and receive:

1. a bounded conclusion, including disconfirming evidence;
2. ranked market-specific actors with decomposable evidence-based scores;
3. normalized beliefs and independent propagation paths;
4. observable company actions and carefully labeled temporal relationships;
5. adjacent markets and dependencies supported by sources;
6. exact citations from immutable document versions;
7. explicit coverage gaps, unresolved identities, and causal limitations;
8. actionable next investigations for a named company;
9. a reproducible run manifest and cost report;
10. no infrastructure beyond the architecture decision unless a deferred trigger was passed.
