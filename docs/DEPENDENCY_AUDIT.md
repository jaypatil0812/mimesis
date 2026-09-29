# Memesis Dependency Audit

Status: decision record for the first vertical slice  
Audit date: 2026-09-29  
Method: current README, license, repository tree, primary dependency manifest, release state, and official service documentation were inspected. Commit identifiers below make the audit reproducible; they are not version pins.

## Decision summary

| Candidate | Decision | Role in the first slice | Principal reason |
|---|---|---|---|
| Graphiti | **BORROW PATTERN** | Temporal/provenance design reference | Valuable semantics, but its graph database and extraction stack duplicate a much smaller PostgreSQL implementation |
| Harken | **BORROW PATTERN** | Adapter, cursor, and normalized-envelope reference | Useful thin collector, but immature and centered on brand mentions rather than evidence-bearing beliefs |
| Crawl4AI | **REJECT** for the first slice | None; keep a replaceable browser-crawl interface | Far more browser, extraction, and model machinery than seeded public pages require |
| OpenAlex API | **USE THROUGH API** | Research metadata, authors, institutions, citations, topics | Excellent structured coverage, CC0 data, and inexpensive bounded queries |
| OpenAlex repository stack | **REJECT** as runtime | Reference only | Reproducing OpenAlex requires Elasticsearch, data warehouses, queues, and a large corpus |
| OpenAlex official CLI | **REJECT** for now | Possible later bulk-import tool | Useful only when API-scale access is no longer sufficient |
| Bluesky Jetstream | **USE THROUGH API** | Filtered live public-post events after historical seeding | Public service provides the useful event stream without multi-terabyte hosting |
| LightRAG | **REJECT** | None | Adds multiple stores and repeated LLM extraction where typed assertions and bounded graph retrieval are required |

No candidate should be forked. A fork would transfer upstream maintenance without creating proprietary advantage.

## Evaluation criteria

Candidates were evaluated for fit with these constraints:

- permissive and understandable licensing;
- self-hosting where it lowers—not raises—risk;
- incremental, cursor-based processing;
- exact source provenance and temporal semantics;
- low infrastructure count and local-development friction;
- deterministic processing before model calls;
- replaceable model providers;
- bounded operating cost;
- overlap with the Memesis proprietary layer.

Operational complexity is rated **low**, **medium**, or **high** relative to one Python service plus PostgreSQL. Cost estimates exclude engineering time and human review.

## 1. Graphiti

Repository: [getzep/graphiti](https://github.com/getzep/graphiti)  
Inspected revision: `ea4ac0f34ee8`; latest observed release `v0.30.2`  
License: Apache License 2.0

### What it is

Graphiti is a Python framework for incrementally constructing temporally aware knowledge graphs from episodes. It preserves source episodes, distinguishes temporal facts, supports custom entity types, and combines semantic, keyword, and graph retrieval. Those are close to Memesis's desired evidence discipline.

### Architecture and dependencies

- ingestion of episodes followed by entity/relationship extraction and graph mutation;
- graph backends including Neo4j, FalkorDB, Amazon Neptune, and a deprecated Kuzu path;
- model and embedding providers behind interfaces, with OpenAI defaults;
- Pydantic-structured extraction and hybrid retrieval;
- Python 3.10+, a graph database, an LLM, an embedding model, and optional reranking;
- anonymous PostHog telemetry unless disabled.

### Decision: BORROW PATTERN

Borrow its separation of source episodes from derived facts, bi-temporal fact handling, incremental invalidation, ontology-constrained extraction, and hybrid candidate retrieval. Do not take it as the first-slice runtime.

Graphiti's value is mostly in semantics that Memesis must own and make stricter. Its graph database, embedding, and model-call assumptions add services and cost before the corpus needs them. Direct adoption would also make Memesis's core assertion ledger and market ontology subordinate to a general framework.

### Obligations, operations, cost, and overlap

- **License obligations:** retain the Apache 2.0 license and notices in redistributed source or substantial copied code; mark modified files; respect the patent grant and termination terms. Mere use as design inspiration does not import code obligations.
- **Operational complexity:** high for the proof—graph database plus model and embedding services, migrations, backups, and telemetry configuration.
- **Expected cost:** graph hosting plus extraction, embeddings, and optional reranking. The dominant variable is LLM calls per episode; it is not bounded without a custom ingestion policy.
- **Overlap:** very high with the proprietary ontology, temporal evidence graph, entity resolution, extraction, and retrieval layers.

## 2. Harken

Repository: [VladUZH/harken](https://github.com/VladUZH/harken)  
Inspected revision: `d0710a427dbb`; package version `0.1.0`; no release observed  
License: MIT

### What it is

Harken is a small self-hosted social-listening application. Adapters collect from Hacker News, Reddit, Mastodon, Bluesky, Stack Overflow, RSS, X, and YouTube; records are normalized and deduplicated; sentiment can be lexicon- or model-based; SQLite and a FastAPI dashboard provide local storage and review.

### Architecture and dependencies

- one adapter interface and common mention envelope;
- cursoring, retry behavior, backfill, hash deduplication, metrics, and local authentication;
- SQLite persistence and FastAPI/Jinja UI;
- principal dependencies: `httpx`, `feedparser`, FastAPI, Uvicorn, Jinja, Typer, Rich, and Pydantic;
- optional source credentials and optional LLM sentiment.

### Decision: BORROW PATTERN

Borrow the small adapter contract, cursor-after-durable-write rule, local-first operability, and simple backfill ergonomics. Reimplement those patterns around Memesis's immutable document/version envelope.

Do not use Harken directly. It is young, lightly adopted, and its unit is a brand mention rather than a versioned document, exact evidence span, belief assertion, or temporal relationship. Its source breadth would also invite policy and terms work before it contributes to the target investigation.

### Obligations, operations, cost, and overlap

- **License obligations:** copied code requires the MIT copyright and permission notice. Pattern-only use creates no code-copy obligation.
- **Operational complexity:** low by itself; medium after replacing its schema and persistence to meet Memesis requirements.
- **Expected cost:** mostly free public endpoints plus any source-specific API fees; optional LLM sentiment is unnecessary. Engineering integration cost is larger than runtime cost.
- **Overlap:** high with collection adapters and scheduling; low with ontology, market graph, and evidence reasoning.

## 3. Crawl4AI

Repository: [unclecode/crawl4ai](https://github.com/unclecode/crawl4ai)  
Inspected revision: `e5d2e786d1a1`; latest observed release `v0.9.4`  
License: Apache License 2.0

### What it is

Crawl4AI is a broad web-crawling and extraction platform with a Python library, server mode, browser automation, caching, deep crawling, stealth/proxy controls, structured extraction, and optional LLM extraction.

### Architecture and dependencies

- Playwright/Patchright browser execution and browser-pool/server modes;
- CSS, XPath, regex, schema, and model-driven extraction;
- crawling strategies, caching, proxy/stealth features, and Markdown generation;
- dependencies include `aiohttp`, `aiosqlite`, `lxml`, Playwright, Patchright, NLTK, Shapely/AlphaShape, and a pinned LiteLLM package, plus optional extras.

### Decision: REJECT for the first slice

Seeded company pages, blogs, docs, and RSS can be collected with ordinary HTTP and extracted with Trafilatura. Browser automation should be an isolated fallback behind the same document contract only after a measured coverage gap.

Crawl4AI is capable, but capability is not the constraint. Its browser runtime, anti-bot surface, optional LLM extraction, and large dependency tree increase deployment and source-policy risk. Its crawling and extraction features overlap with work Memesis needs to control at the provenance boundary.

### Obligations, operations, cost, and overlap

- **License obligations:** Apache 2.0 notice, attribution, changed-file, and patent terms apply if code is redistributed. Its README also requests attribution; any future adoption should reconcile README language against the repository license and retain attribution conservatively.
- **Operational complexity:** high relative to bounded HTTP collection—browser binaries, memory, process lifecycle, anti-bot failures, proxies, and broader security hardening.
- **Expected cost:** local browser CPU/RAM; potentially material proxy and CAPTCHA expense; optional LLM costs. There is no need to incur these in the proof.
- **Overlap:** high with fetch, cleaning, extraction, caching, and crawling policy; low with graph reasoning.

## 4. OpenAlex API

Service: [OpenAlex API](https://help.openalex.org/api/)  
Terms/data: [How OpenAlex data is built and licensed](https://help.openalex.org/data/how-its-built/)  
Pricing: [API example costs](https://help.openalex.org/access/example-costs/)

### What it is

OpenAlex is a large structured catalog of scholarly works, authors, institutions, sources, topics, funders, and their relationships. The REST API supports singleton lookup, filters, search, grouping, and cursor pagination.

### Architecture and dependencies

Memesis needs no OpenAlex client runtime. A small HTTP adapter maps API responses into source documents and stable external identifiers. The adapter must use cursor paging, conditional incremental queries where available, response caching, and a strict per-investigation field selection.

### Decision: USE THROUGH API

Use metadata, abstracts when available, authorship, affiliation, topic, citation, and DOI relationships for the bounded research corpus. Do not mirror the dataset and do not bulk-download PDFs. OpenAlex gives strong identifiers and provenance at negligible first-slice cost.

### Obligations, operations, cost, and overlap

- **License obligations:** OpenAlex metadata is released under CC0. Full-text content linked or delivered by OpenAlex retains its original copyright/license; each work's license must be checked before storage or redistribution.
- **Operational complexity:** low—one authenticated REST adapter, pagination, rate limiting, and schema-version tests.
- **Expected cost:** at the audited price, an API key includes a free daily budget; list/filter calls are inexpensive and singleton gets are free. A tightly bounded investigation should remain in the free allowance. Content downloads are separately priced and excluded.
- **Overlap:** supplies research entities and citation relationships, but not Memesis belief extraction, influence scoring, or company-action history.

## 5. OpenAlex repositories

The `ourresearch` organization contains several related repositories. They are not interchangeable dependencies.

### openalex-elastic-api

Repository: [ourresearch/openalex-elastic-api](https://github.com/ourresearch/openalex-elastic-api)  
Inspected revision: `61d0ecd92f11`  
License: MIT  
Decision: **REJECT as runtime**

This is the API application and depends on Flask, Elasticsearch, Redis, PostgreSQL/Databricks integrations, and LLM-related packages. Self-hosting it does not create the underlying OpenAlex corpus. License obligations are the MIT notice if copied. Operational complexity and data costs are high; overlap is entirely with a service available more cheaply through the public API.

### openalex-guts

Repository: [ourresearch/openalex-guts](https://github.com/ourresearch/openalex-guts)  
Inspected revision: `8b0e87d0589a`  
License: MIT  
Decision: **REJECT**

This is a large, older processing backend with PostgreSQL, Redshift, Redis, Elasticsearch, and pinned legacy dependencies. It is useful as an implementation reference only. MIT notice obligations apply to copied code. Operational complexity is very high, cost includes the data warehouse and search estate, and it overlaps with OpenAlex's managed production pipeline rather than Memesis's product layer.

### openalex-walden

Repository: [ourresearch/openalex-walden](https://github.com/ourresearch/openalex-walden)  
Inspected revision: `c65105103f1a`  
License: MIT  
Decision: **REJECT**

This repository contains current data-pipeline jobs and Databricks-oriented notebooks/configuration. It is relevant only to rebuilding OpenAlex. MIT notice obligations apply to copied code. Operational complexity and compute/storage cost are very high; there is no first-slice overlap beyond data the API already exposes.

### openalex-official

Repository: [ourresearch/openalex-official](https://github.com/ourresearch/openalex-official)  
Inspected revision: `183ff7cd1997`; latest observed release `v0.3.3`  
License: MIT  
Decision: **REJECT for now; reconsider for bulk acquisition**

The official CLI supports bulk metadata and content acquisition with asynchronous S3/API access. Its main dependencies are `aiohttp`, `aiobotocore`, Click, Rich, and Tenacity. It is simple compared with the backend repositories, but the proof does not need bulk files. MIT notice obligations apply if distributed. Operational complexity is medium because downloaded content requires storage, checkpointing, and rights review; API calls are the cheaper, narrower substitute.

## 6. Bluesky Jetstream

Repository: [bluesky-social/jetstream](https://github.com/bluesky-social/jetstream)  
Inspected revision: `3fa54fdbb0f4`; latest observed release `v0.2.5`  
License: dual MIT or Apache License 2.0

### What it is

Jetstream transforms the AT Protocol firehose into simpler JSON events and supports collection/repository filters, cursors, live consumption, archive, and replay. It is a Go service optimized for the whole public network, not a search index.

### Architecture and dependencies

- websocket live stream with server-side collection and DID filters;
- at-least-once delivery, so consumers must deduplicate by sequence/cursor;
- delete, account, identity, and synchronization events that consumers must fold into state;
- compressed archive and replay paths;
- static Go service, but self-hosted archive/backfill requires substantial storage and memory.

### Decision: USE THROUGH API

Use Bluesky AppView search to seed historical posts and the public Jetstream v2 endpoint for narrow, forward-looking filters after the seed is stable. Persist the cursor transactionally, process tombstones, and retain only records allowed by the source policy.

Do not self-host a whole-network archive. Public infrastructure supplies the slice Memesis needs; hosting multiple terabytes to capture a few actors and keywords is the opposite of the stated architecture principle.

### Obligations, operations, cost, and overlap

- **License obligations:** if redistributing Jetstream code, select and comply with one offered license; Apache 2.0 is the clearer default for a commercial codebase. API use does not import its code license. Public posts remain third-party content subject to applicable rights and platform terms.
- **Operational complexity:** low-to-medium as an API consumer; high as a full-network host. The consumer needs reconnect, dedupe, cursor, tombstone, and lag handling.
- **Expected cost:** live public endpoints have no published usage charge. Replay is API-key controlled and metered by compressed bytes, with no public dollar schedule observed; broad replay is therefore excluded from the baseline budget.
- **Overlap:** event transport only. It does not perform search-quality historical discovery, entity resolution, belief extraction, or scoring.

## 7. LightRAG

Repository: [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG)  
Inspected revision: `453dce83d6d0`; latest observed release `v1.5.7`  
License: MIT

### What it is

LightRAG is a graph-augmented retrieval framework with server, SDK, and Web UI. It extracts entities and relationships from chunks, maintains multiple logical stores, and supports local, global, hybrid, and mix query modes.

### Architecture and dependencies

- separate key-value, vector, graph, and document-status abstractions;
- multiple LLM roles for extraction, summarization, and query generation;
- embeddings and optional reranking;
- production backends such as PostgreSQL or MongoDB/OpenSearch plus graph/vector options;
- broad provider and parser dependencies, including model SDKs, `nano-vectordb`, NetworkX, and Pandas.

### Decision: REJECT

Memesis does not need generic document chat. It needs source-versioned atomic assertions, explicit temporal relationships, conservative identity, source-independence controls, and reproducible market scores. LightRAG's automatic chunk-to-graph workflow would create repeated model work and opaque graph mutations while duplicating PostgreSQL storage and Memesis retrieval.

### Obligations, operations, cost, and overlap

- **License obligations:** MIT notice and copyright retention if code is copied or distributed.
- **Operational complexity:** high—several logical stores, provider configuration, index lifecycle, and model-dependent rebuilds.
- **Expected cost:** embeddings for the corpus, LLM extraction and summarization across chunks, reranking, and query-time model calls. Cost rises with corpus size even when most text is irrelevant.
- **Overlap:** very high with extraction, graph construction, retrieval, and reasoning; low fit with required provenance controls.

## Better alternatives considered

| Alternative | License | Decision | Reason |
|---|---|---|---|
| [PostgreSQL](https://www.postgresql.org/) | PostgreSQL License | **USE DIRECTLY** | One permissive durable store provides relational constraints, JSON, full-text search, trigram matching, queues, and bounded graph traversal |
| [pgvector](https://github.com/pgvector/pgvector) | PostgreSQL License | **DEFER** | Best low-infrastructure vector option, but only add it if lexical/graph retrieval fails a measured relevance gate |
| [Trafilatura](https://github.com/adbar/trafilatura) | Apache-2.0 | **USE DIRECTLY** | Focused HTML text/metadata extraction without a browser runtime or LLM |
| [Scrapling](https://github.com/D4Vinci/Scrapling) | BSD-3-Clause | **DEFER** | Stronger dynamic-page/anti-bot capability, but unnecessary and policy-heavy until a documented source cannot be collected otherwise |
| [Microsoft GraphRAG](https://github.com/microsoft/graphrag) | MIT | **REJECT** | Batch- and model-heavy generic graph RAG; same mismatch as LightRAG |
| [Cytoscape.js](https://github.com/cytoscape/cytoscape.js) | MIT | **USE DIRECTLY** | Mature client-side graph rendering with no graph-server commitment |
| Neo4j Community | GPLv3 | **REJECT for first slice** | Additional service and reciprocal distribution questions with no demonstrated query need |
| FalkorDB | source-available terms | **REJECT for first slice** | Additional service and less permissive licensing than PostgreSQL |

## Selected dependency surface

The first implementation should depend on:

- PostgreSQL and its built-in full-text/trigram/recursive-query capabilities;
- Python, FastAPI, Pydantic, an HTTP client, a feed parser, and Trafilatura;
- OpenAlex REST, Bluesky AppView/Jetstream, Hacker News Algolia, GitHub's official API/release feeds, RSS/Atom, and ordinary HTTP;
- React/TypeScript and Cytoscape.js for the investigation UI;
- one replaceable small extraction model and one replaceable stronger synthesis model.

Every external source and model is behind an internal interface. No selected repository owns Memesis's canonical IDs, evidence ledger, ontology, scores, or decision methodology.
