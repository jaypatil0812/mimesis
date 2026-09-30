# Memesis: Codebase Reality Audit

**Audit Date**: September 30, 2026  
**Auditor**: Founding Technical Architect (Memesis Core)  
**Standard**: Strict Empirical Execution (No README claims accepted; every path executed and verified live)

---

## 1. Executive Summary & Layer Scorecard

| Layer | Status | Implementation File(s) | Empirical Verdict |
| :--- | :--- | :--- | :--- |
| **1. Collectors** | **PARTIAL** | `src/memesis/sources/` (`hackernews.py`, `openalex.py`, `bluesky.py`, `rss.py`, `web.py`) | HN, OpenAlex, Bluesky, and RSS connect and fetch live data over the network. `web.py` (Crawl4AI) fails on 404 `robots.txt` checks and requires local Chromium browser dependencies. |
| **2. Normalization** | **WORKING** | `src/memesis/ingestion/normalizer.py` | NFC Unicode normalization, whitespace collapsing, boilerplate removal, SHA-256 hashing. Fully verified. |
| **3. Deduplication** | **WORKING** | `src/memesis/ingestion/service.py`, `sql_repository.py` | SHA-256 payload deduplication prevents duplicate raw and normalized documents from re-entering graph. |
| **4. Raw Evidence Storage** | **WORKING** | `src/memesis/graph/sql_repository.py`, `db/models.py` | Immutable payloads stored in `document`, `document_version`, and `evidence` SQL tables with exact character spans. |
| **5. Provenance** | **WORKING** | `src/memesis/domain/schemas.py`, `graph/sql_repository.py` | Strict `Provenance` model attaches source URLs, retrieved/published timestamps, exact quotes, and entity IDs to every edge and node. |
| **6. Entity Extraction** | **PARTIAL** | `src/memesis/extraction/deterministic.py`, `model.py` | High-precision regex rules extract executive roles, company affiliations, and product launches. Ambiguity model fallback exists but requires external API key. |
| **7. Entity Resolution** | **PARTIAL** | `src/memesis/extraction/resolution.py` | Alias tables and external identifier matching (e.g. OpenAlex IDs). Does not merge on name similarity alone, but lacks semantic resolution for homonyms/acronyms without LLM. |
| **8. Belief Extraction** | **PARTIAL** | `src/memesis/extraction/deterministic.py` | Regex patterns extract propositional verbs (`will`, `should`, `replace`, `reduce`). Extracts explicit claims well, but misses complex conversational arguments. |
| **9. Belief Deduplication** | **PARTIAL** | `src/memesis/extraction/pipeline.py` | Deduplicates identical propositional strings. Semantic near-duplicate clustering currently relies on heuristic token overlap. |
| **10. Relationship Extraction** | **PARTIAL** | `src/memesis/extraction/pipeline.py` | Generates `PUBLISHED`, `EXPRESSES`, `WORKS_AT`, `FOUNDED`, `BUILDS`, `ACTS_ON`. Regex-bound; struggles with multi-clause compound sentences. |
| **11. Temporal Handling** | **WORKING** | `src/memesis/graph/sql_repository.py` | ISO timestamps enforced. Future-dated evidence (`> now + 1 day`) rejected. Retrospective `as_of` queries prevent future data leakage. |
| **12. Graph Persistence** | **WORKING** | `src/memesis/graph/sql_repository.py` | SQLite & PostgreSQL storage using JSON columns for attributes and provenance. 75 nodes, 44 edges seeded and operational. |
| **13. Graph Retrieval** | **WORKING** | `src/memesis/graph/sql_repository.py`, `retrieval/context_builder.py` | Recursive SQL CTE (`WITH RECURSIVE walk...`) retrieves bounded k-hop subgraphs up to 8 hops. Bounded pruning works. |
| **14. Scoring** | **WORKING** | `src/memesis/analysis/scoring.py` | 6 deterministic scores: `ActorLead`, `ActorInfluence` (propagation-gated), `BeliefVelocity`, `BeliefDiversity` (source-gated), `ActionConversion`, `EvidenceConfidence`. Completely transparent, zero LLM vibes. |
| **15. Historical Analogues** | **WORKING / HYBRID** | `src/memesis/reasoning/historical_analogues.py` | Deterministic structural pattern matcher (*Microservices 2012*, *RISC vs CISC 1980s*, *NLP Distillation 2019*). Analogue bank is currently hardcoded. |
| **16. Jev / DecisionEngine** | **STUB / HEURISTIC** | `src/memesis/reasoning/decision_engine.py` | Implements `HeuristicDecisionEngine` with regex/keyword rules (`jev-heuristic-v0.1`). Real TypeSafe AI Jev API integration (`POST /v1/systemone`) is **MISSING**. |
| **17. Deep Reasoning Gate** | **WORKING / UNVALIDATED**| `src/memesis/reasoning/deep_gate.py` | Evaluates query ambiguity, graph coverage gaps, and contradictions to decide whether to trigger frontier reasoning. Tested in unit suite. |
| **18. Claim Validation** | **WORKING** | `src/memesis/reasoning/validator.py` | Enforces epistemic status (`OBSERVED`, `INFERRED`, `SPECULATIVE`). Uncited claims downgraded; speculative claims stripped of absolute language. |
| **19. Confidence** | **WORKING** | `src/memesis/reasoning/confidence.py` | Deterministic score aggregating evidence counts, cross-corroboration, and coverage gaps. |
| **20. Frontend** | **WORKING** | `frontend/` (Next.js 14, Tailwind, TypeScript) | 7-tab Market Workspace (**Overview**, **People**, **Beliefs**, **Companies**, **Timeline**, **Graph**, **Ask Memesis**). Compiles with zero errors. |
| **21. API** | **WORKING** | `src/memesis/web/api.py`, `app.py` | Clean REST JSON API (`/api/markets`, `/api/markets/{id}`, `/api/markets/{id}/ask`) with CORS. Sub-80ms latency. |
| **22. Profiling** | **WORKING** | `src/memesis/profiler/pipeline_profiler.py`, `optimizer.py` | Read-only profiler measures 5 stages and ranks bottlenecks. `--optimize` runs before/after benchmarks with automated quality regression testing. |
| **23. Adversarial Tests** | **WORKING** | `tests/test_adversarial.py` | 14 automated adversarial tests covering entity merges, fake causality, popularity vs influence, bot swarms, and hindsight bias. 14/14 passing. |

---

## 2. In-Depth Layer Breakdown

### Layer 1: Collectors (`src/memesis/sources/`)
* **Hacker News (`hackernews.py`)**: Uses Algolia API (`https://hn.algolia.com/api/v1/search_by_date`). Verified live: successfully retrieves real comments and stories with authors, Unix timestamps, and external URLs.
* **OpenAlex (`openalex.py`)**: Uses public OpenAlex REST API (`https://api.openalex.org/`). Verified live: searches works, authors, topics, and institutions with citations and canonical IDs.
* **Bluesky (`bluesky.py`)**: Uses Bluesky public AppView (`https://api.bsky.app/xrpc/app.bsky.feed.searchPosts`). Verified live: fetches real developer and practitioner posts.
* **RSS (`rss.py`)**: Pure Python XML parser using `urllib`/`httpx`. Verified live against Hacker News RSS and standard feeds.
* **Web Crawl4AI (`web.py`)**: **PARTIAL / BUGGY**. The collector checks `robots.txt` before crawling. If `robots.txt` returns HTTP 404 (standard web behavior meaning *no restrictions apply*), the HTTP client raises `HTTPStatusError` instead of treating 404 as allowed. Furthermore, `playwright install chromium` is required on the host system.

### Layer 6 & 7: Entity Extraction & Resolution (`src/memesis/extraction/`)
* Deterministic extraction matches patterns like `Sam Altman (CEO of OpenAI)` or `Acme Corp launched ModelX`.
* Entities are stored with aliases and external IDs.
* **Limitation**: Real unstructured text often contains subtle references (*"the former head of hardware at Google"*, *"the team behind vLLM"*). Currently, deterministic extraction misses these unless an explicit model fallback is provided.

### Layer 8 & 9: Belief Extraction & Deduplication
* Distinguishes topics from falsifiable propositions (e.g. topic: *"small models"*, belief: *"small specialized models will replace frontier models for enterprise inference"*).
* Deduplication currently canonicalizes on identical normalized strings. Two semantically identical beliefs phrased with different grammar are treated as distinct beliefs unless mapped by an ambiguity model or Jev `BELIEF_EQUIVALENCE`.

### Layer 16: Jev / DecisionEngine (`src/memesis/reasoning/decision_engine.py`)
* **Current State**: The codebase defines a `DecisionEngine` Protocol and implements `HeuristicDecisionEngine` (`jev-heuristic-v0.1`), which uses deterministic keyword overlap and score thresholds.
* **Missing**: `TypeSafeJevDecisionEngine` connecting to `https://api.typesafe.ai/v1/systemone` (or OpenRouter Jev fallback) with support for `CHOICE`, `SCORE`, and `NOUL` primitives.

### Layer 20: Product Frontend (`frontend/`)
* Production Next.js 14 App Router application with Tailwind CSS and Lucide icons.
* Single Market Workspace featuring 7 functional tabs:
  1. `Overview`: Subgraph counts, edge metrics, adjacent market tags.
  2. `People`: Actors with Lead Scores and Propagation-Gated Influence Scores.
  3. `Beliefs`: Tracked propositions with velocity and bot-resistant diversity metrics.
  4. `Companies`: Commercial participants with graph relationship tags.
  5. `Timeline`: Chronological evidence feed with source URLs.
  6. `Graph`: Adjacency matrix of connected nodes and edges.
  7. `Ask Memesis`: Asynchronous query console with epistemic claim categorization (Observed, Inferred, Speculative).
* Verified: Builds cleanly (`npm run build`) with zero errors.

---

## 3. Real Gaps & Required Implementation Tasks (Phase 9)

1. **Fix `robots.txt` 404 Bug in Web Collector**: Allow 404 on `robots.txt` to pass as allowed.
2. **Implement Real TypeSafe Jev Integration**: Create `TypeSafeJevDecisionEngine` targeting `POST /v1/systemone` using `TYPESAFE_API_KEY`, supporting `CHOICE`, `SCORE`, and `NOUL`, with provider fallback to `HeuristicDecisionEngine` and OpenRouter Jev 1.13.
3. **Ingest Real Public Corpus**: Collect 500–2,000 real evidence objects on *AI Inference / Small Specialized Models* across Hacker News, OpenAlex, Bluesky, RSS, and Web blogs.
4. **Implement Perception Intelligence Schema**: Add first-class support for `People/Community → Perception → Product/Company/Market` across dimensions (`PAIN`, `PRAISE`, `FEATURE_REQUEST`, `SWITCHING_INTENT`, `PRICE_SENSITIVITY`, etc.).
5. **Run Gold Evaluation Benchmark**: Benchmark `TypeSafe Jev` vs `HeuristicDecisionEngine` vs `Frontier LLM` on bounded judgments (`RELEVANCE`, `BELIEF_EQUIVALENCE`, `PERCEPTION_CATEGORY`, `CLAIM_SUPPORT`) $\rightarrow$ `docs/DECISION_ENGINE_BENCHMARK.md`.
6. **Execute Retrospective Historical Replay**: Verify that pre-cutoff evidence correctly signals market movement without future leakage.
7. **Produce Baseline vs. Memesis Comparison**: Compare Memesis against a pure frontier research workflow on the AI inference question $\rightarrow$ `reports/BASELINE.md`, `reports/MIMESIS.md`, `reports/COMPARISON.md`.
