<div align="center">

# MEMESIS

### Evidence-Bound Market Intelligence & Provenance Graph

[![Tests](https://img.shields.io/badge/Tests-Source%20suite-blue?style=flat-square&logo=pytest)](tests/)
[![Python](https://img.shields.io/badge/Python-3.12+-blue?style=flat-square&logo=python)](pyproject.toml)
[![Frontend](https://img.shields.io/badge/Frontend-Next.js%2014%20%7C%20Tailwind-black?style=flat-square&logo=next.js)](frontend/)
[![Architecture](https://img.shields.io/badge/Architecture-Provenance--First-purple?style=flat-square)](docs/ARCHITECTURE.md)
[![License](https://img.shields.io/badge/License-Apache%202.0%20%2F%20MIT-green?style=flat-square)](docs/LICENSES.md)

**Memesis maps how beliefs become markets.** It is a provenance-first intelligence system that tracks:
`PERSON → BELIEF → CONTENT → PROPAGATION → COMPANY ACTION → MARKET → OUTCOME`

[Core Thesis](#-core-thesis) •
[System Architecture](#-architecture) •
[Interactive Workspace](#-product-ui) •
[Methodology & Scoring](#-scoring-methodology) •
[Quickstart](#-quickstart) •
[CLI & Profiler](#-cli--profiler) •
[Adversarial Hardening](#-adversarial-testing)

</div>

## Reliable connected memory update

The [current implementation guide](docs/RELIABLE_MARKET_INTELLIGENCE.md) covers query-dependent relevance, reviewable perception candidates, sourced historical comparisons, repeated webpage collection, provider usage accounting and the **Investigations & review** interface. Fixed market reports and unsupported provider savings claims have been withdrawn.

Draft diagnostic cases cover batteries, agriculture, industrial heat and insufficient evidence. Human semantic review and customer validation remain pending. Model configuration and a separately running worker are required for live strategic reasoning and continuous collection.

---

Current local backend additions: [evidence-dependent answers](docs/EVIDENCE_REASONING.md)
and [continuous bounded investigations](docs/INVESTIGATIONS.md).
Quality is assessed through [layer diagnostics and human decision review](docs/INTELLIGENCE_EVALUATION.md).
Extraction and stored-memory upgrades follow [market-neutral extraction and controlled rebuilds](docs/MARKET_NEUTRAL_EXTRACTION.md).

## 🎯 The Core Thesis

Most AI market intelligence fails in two ways:
1. **The Naive RAG / Scraping Dump**: Crawling thousands of web pages, passing them into an expensive frontier LLM ($0.20–$1.00/query), and asking for strategic insights. This results in hallucinations, lacks temporal understanding, and cannot tell whether a narrative is organic or bot-amplified.
2. **The Keyword & Follower Counter**: Mistaking follower counts for genuine influence, or treating simultaneous community discussions as causal adoption.

**Memesis takes a deterministic, evidence-bound approach:**
- **Collect once, normalize once, extract once**: All raw sources (Web, ArXiv/OpenAlex, RSS, Bluesky, Hacker News) are stored with SHA-256 content hashes and immutable timestamps.
- **Provenance attached to every claim**: No edge exists in the graph without exact character spans and source URLs.
- **Cheap deterministic filtering**: Over 40+ Jev-style heuristic decisions filter and bound subgraphs before any reasoning model is touched.
- **Sub-80ms queries at \$0.00 cost**: Standard queries execute deterministically against the structured graph, invoking reasoning models only for high-entropy synthesis.

---

## 🏗️ Architecture

```
RAW INTERNET SIGNALS (Web, Papers, RSS, Social)
  │
  ▼
EVIDENCE LEDGER (Immutable raw payloads, SHA-256 hashes, exact character offsets)
  │
  ▼
CANONICAL KNOWLEDGE GRAPH (Entities: Person, Company, Belief, Market, Product, Event)
  │
  ├── DETERMINISTIC SCORING ENGINE (Lead, Propagation-Gated Influence, Velocity, Diversity)
  │
  ▼
QUERY INTENT CLASSIFIER & PLANNER
  │
  ▼
JEV DECISION ENGINE (Cheap heuristic sub-graph bounding — zero LLM tokens)
  │
  ▼
MINIMUM SUFFICIENT SUBGRAPH RETRIEVAL (Bounded k-hop entity context)
  │
  ├── HISTORICAL ANALOGUE ENGINE (Matches structural patterns like Microservices 2012)
  │
  ▼
EVIDENCE VALIDATOR (Enforces epistemic status: OBSERVED, INFERRED, SPECULATIVE)
  │
  ▼
STRATEGIC SYNTHESIS (Compact, hallucination-free executive intelligence)
```

---

## 💻 Product UI: The Market Workspace

Memesis features a functional, lightweight product frontend built with **Next.js 14**, **TypeScript**, and **Tailwind CSS**, communicating with the **FastAPI** backend via a clean REST API.

All intelligence is organized into a single tabbed **Market Workspace**:

| Tab | Purpose | What You See |
| :--- | :--- | :--- |
| **Overview** | Market vitals & summary | High-level topology stats, node counts, edge counts, and adjacent market boundaries |
| **People** | Key market actors | Measured **Actor Lead** (early commentary) and **Actor Influence** (propagation-verified) scores |
| **Beliefs** | Tracked hypotheses | Core market belief propositions with **Velocity** and **Diversity** metrics |
| **Companies** | Commercial participants | Organizations acting on or serving the market with graph relationship tags (`BUILDS`, `SERVES`, `ACTS_ON`) |
| **Timeline** | Immutable evidence ledger | Chronologically sorted primary evidence items with source links and publication dates |
| **Graph** | Structural topology | Adjacency relationship matrix displaying all directional entity edges |
| **Ask Memesis** | Asynchronous query engine | Interactive strategic console delivering structured, verified market answers |

### Epistemic Claim Segmentation

Every answer generated by **Ask Memesis** categorizes assertions by proof standard:
- 🟢 **OBSERVED**: Direct facts backed by cited primary evidence in the graph.
- 🟡 **INFERRED**: Logical conclusions derived from observed relations across multiple entities.
- 🟣 **SPECULATIVE**: Forward-looking implications, platform risks, and predictions (strictly hedged).

---

## 📐 Scoring Methodology

Memesis rejects vibe-based AI scores. Every metric is transparent, decomposable, and replayable:

### 1. Actor Lead Score
Measures whether an actor expressed belief $B$ **before** other independent groups and companies acted.
$$\text{Lead} = f(\text{temporal\_lead}, \text{downstream\_adoption}, \text{commercial\_followthrough})$$

### 2. Actor Influence Score (Propagation-Gated)
**Popularity and follower counts are not sufficient evidence of influence.**
Influence requires evidence of the causal chain:
$$\text{Actor expresses belief} \longrightarrow \text{Independent actors propagate/cite it} \longrightarrow \text{Companies act}$$
If an actor has **zero explicit propagation edges** (`INFLUENCES` / `AMPLIFIES`), general market adoption cannot be credited to them. Their influence score is strictly gated ($\le 25.0$). Furthermore, amplifier accounts with zero authentic published expressions carry an 80% discount factor.

### 3. Belief Velocity
Measures momentum and acceleration of belief expressions across sliding historical time windows:
$$\text{Momentum} = 50 + 50 \times \frac{\text{current\_expressions} - \text{previous\_expressions}}{\text{total\_expressions}}$$

### 4. Belief Diversity (Bot-Resistant)
Measures source family entropy, organizational breadth, and stance breadth.
To prevent bot swarms from manufacturing consensus:
$$\text{effective\_actor\_entropy} = \text{actor\_entropy} \times \min\left(1.0, 0.20 + 0.80 \times \frac{\text{source\_family\_entropy}}{100.0}\right)$$
When all expressions originate from a single source domain (e.g. 50 bot accounts on Twitter), `source_family_entropy` is 0, capping actor entropy at 20%.

---

## ⚡ Quickstart

### Prerequisites
- Python 3.12+
- Node.js 18+ & npm
- [uv](https://github.com/astral-sh/uv) (recommended Python package manager)

### 1. Clone & Setup Backend

```bash
git clone https://github.com/vdnthtml/mimesis.git
cd mimesis

# Sync Python environment and lockfile
uv sync

# Configure local development environment
cp .env.example .env
# .env.example defaults to PostgreSQL. For the seeded local preview, set:
# MEMESIS_DATABASE_URL=sqlite:///./memesis-phase5.sqlite3

# Check system health
uv run memesis health
```

### 2. Run the Test Suite

```bash
# Run all 52 unit and adversarial tests
uv run pytest -v
```

### 3. Launch Backend & Frontend

In **Terminal 1** (Backend):
```bash
uv run uvicorn memesis.app:app --host 0.0.0.0 --port 8000 --reload
# FastAPI interactive documentation at: http://localhost:8000/docs
```

In **Terminal 2** (Frontend):
```bash
cd frontend
npm install
npm run dev
# Next.js Market Workspace at: http://localhost:3000
```

---

## 🛠️ CLI & Profiler

Memesis includes a comprehensive command-line interface for headless operations and pipeline profiling:

### Strategic Query Answering (`memesis ask`)
Query the graph directly from the terminal with full provenance output:
```bash
uv run memesis ask "Is model routing replacing single frontier models in production?"
```

### Read-Only Pipeline Profiler (`memesis profile`)
Measures wall-clock time, DB queries, token usage, and LLM cost across all 5 execution stages without altering any system state:
```bash
uv run memesis profile "Is model routing replacing single frontier models in production?"
```
*Outputs ranked bottlenecks and categorizes optimizations into Safe Predetermined vs. Prohibited (requiring manual approval).*

### Safe Optimizer Benchmark (`memesis profile --optimize`)
Applies safe, predetermined optimizations (daily snapshot caching, in-memory query deduplication), runs before/after benchmarks, and verifies zero answer quality regression:
```bash
uv run memesis profile --optimize "Is model routing replacing single frontier models in production?"
```

### Compute Historical Scores (`memesis compute-scores`)
Replay deterministic scoring calculations idempotently at an explicit historical cutoff date:
```bash
uv run memesis compute-scores --as-of 2026-09-29T00:00:00+00:00 --window-days 30
```

---

## 🛡️ Adversarial Testing

Memesis is tested against 14 automated adversarial attack vectors in [`tests/test_adversarial.py`](tests/test_adversarial.py):

1. **Bad Entity Merges**: Distinct entities sharing names are never conflated.
2. **Fake Causality**: Reversed `PRECEDES` edges do not inflate velocity.
3. **Popularity vs. Influence**: High mention counts without propagation edges cap influence at $\le 25.0$.
4. **Correlation vs. Propagation**: Simultaneous community adoption does not create spurious causal edges.
5. **Duplicate Beliefs**: Identical texts are content-hash deduplicated at graph projection.
6. **LLM Hallucinations**: Claims citing non-existent evidence IDs are downgraded to `INFERRED`.
7. **Missing Evidence**: Gaps trigger explicit fallback notices (`INSUFFICIENT EVIDENCE`).
8. **Future Timestamps**: Evidence dated $>1$ day in the future is rejected with `ValueError`.
9. **Source Bias**: Single-domain saturation flags coverage gap warnings.
10. **Echo Chamber Detection**: Single-community discussion produces near-zero source entropy.
11. **Bot Amplification Gating**: High-density amplification from empty accounts caps influence at $\le 40.0$.
12. **Single-Source Bot Swarms**: 50 bot accounts on a single domain cap belief diversity at $\le 20.0$.
13. **Survivorship Bias**: Missing counter-evidence is flagged in `unknown_or_missing`.
14. **Hindsight Bias**: Retrospective queries with `as_of=cutoff` never leak future data.

---

## 📦 Project Structure

```
mimesis/
├── frontend/                     # Next.js 14 App Router product workspace
│   ├── app/                      # Layout, styling, and page components
│   ├── components/               # Tabbed Market Workspace & UI cards
│   └── lib/                      # Typed API client and TypeScript definitions
├── src/memesis/
│   ├── analysis/                 # Deterministic scoring (Lead, Influence, Velocity, Diversity)
│   ├── domain/                   # Canonical Pydantic schemas (Person, Belief, Company, Market, etc.)
│   ├── graph/                    # Repository interface & recursive SQL implementation
│   ├── ingestion/                # HTTP fetchers, rate limiting, and content normalization
│   ├── profiler/                 # Read-only pipeline profiler and safe optimizer
│   ├── reasoning/                # Query classifier, planner, Jev decision filter, synthesizer
│   ├── retrieval/                # Minimum sufficient subgraph context builder
│   ├── sources/                  # Connectors (Web/Crawl4AI, OpenAlex, Bluesky, Hacker News, RSS)
│   ├── app.py                    # FastAPI entrypoint with CORS
│   ├── cli.py                    # Headless CLI entrypoint
│   └── config.py                 # Environment configuration
├── tests/                        # 52 unit, integration, and adversarial tests
├── data/                         # Evaluation datasets and evaluation reports
├── docs/                         # Architecture, ontology, and dependency specifications
└── memesis-phase5.sqlite3        # Pre-seeded reference database fixture
```

---

## 📜 License

Licensed under the [Apache License, Version 2.0](LICENSE).
Approved open-source dependency stack audited in [`docs/DEPENDENCY_AUDIT.md`](docs/DEPENDENCY_AUDIT.md).


## Local backend integration

Connected market memory is documented in [CONNECTED_MARKET_MEMORY.md](docs/CONNECTED_MARKET_MEMORY.md).
It adds typed, source-backed observation candidates, reviewed identity and belief
connections, source families, and transactional graph promotion/retraction. Review
the queue through `/api/memory/observations`; a backfill is not proof of extraction quality.

This checkout includes the Phase 9 collectors, perception intelligence and Jev integration,
plus evidence citation auditing and market/date scoping. See
[market and date scoping](docs/MARKET_SCOPING.md) for scope semantics and API examples.

Answers expose citation integrity separately from semantic support. Optional claim support
verification is enabled with `MEMESIS_VERIFY_CLAIM_SUPPORT=true` and an OpenAI-compatible
model configured through `MEMESIS_MODEL_API_KEY` and `MEMESIS_REASON_STRONG_MODEL`.
Hypotheses remain available even when their supporting evidence is incomplete.

The bundled database contains the Phase 9 collected corpus. Serving the UI does not
automatically start continuous ingestion. Without provider credentials, the hybrid
decision engine uses its offline fallback; those decisions are not live Jev calls.
