# Memesis Cost Model

Status: planning model for the first vertical slice  
Price snapshot: 2026-09-29  
Currency: USD, excluding engineering and analyst labor

## Cost objective

The first investigation should be cheap because each document is collected, normalized, and extracted once. Repeated questions reuse structured knowledge and send only a small evidence packet to a reasoning model.

Targets:

- **initial investigation variable spend:** under **$5**, excluding human review;
- **repeat answer over an unchanged graph:** under **$1**;
- **small hosted proof:** plan for **$20–$75/month** before meaningful traffic;
- **hard model-call budget:** enforced per run and per investigation, with no silent overage.

These are design constraints, not vendor quotes.

## Unit-cost model

For any model call:

```text
call_cost = input_tokens / 1,000,000 × input_price
          + output_tokens / 1,000,000 × output_price
          + provider-specific tool/cache charges
```

For an investigation:

```text
total_variable_cost = collection_api_cost
                    + extraction_cost_for_new_hashes
                    + optional_embedding_cost_for_new_text
                    + synthesis_and_verification_cost
                    + incremental_compute/storage
```

The database records tokens and calculated cost for every model call. A provider price table is versioned by effective date so old runs remain reproducible after price changes.

## Model assumptions

Production code uses capability aliases, not model names:

| Alias | Job | Required behavior | Default budget policy |
|---|---|---|---|
| `extract_small` | Typed extraction from selected spans | Structured output, exact-span references, low latency | Cheapest model that passes the fixture quality gate |
| `resolve_small` | Explain ambiguous candidate pairs for review | Structured comparison; never authorizes merges | Off by default; invoke only for unresolved high-value pairs |
| `reason_strong` | Synthesize one evidence packet | Strong instruction following and calibrated uncertainty | One primary call and at most one repair/verification call |

For a concrete sensitivity example, the audited [official OpenAI pricing](https://developers.openai.com/api/docs/pricing) snapshot lists short-context Standard rates for GPT-6 Luna at $0.10 per million input tokens and $0.50 per million output tokens, and GPT-6 Sol at $2 per million input tokens and $10 per million output tokens. These examples do not make OpenAI a hard dependency; the gateway must support a replacement provider or local model.

## First-investigation scenario

Conservative planning workload:

| Stage | Assumption | Cost treatment |
|---|---|---|
| Discovery | 500 metadata/content records across approved sources | Mostly free endpoints; cache every response |
| Deterministic filtering | 200 records retained as relevant; 300 excluded without a model | Local CPU only |
| Extraction | 300,000 input tokens and 60,000 output tokens across new relevant span packs | At Luna example rates: **$0.06** |
| Extraction contingency | Validation repair/retry and a more expensive fallback on difficult records | Reserve **$0.50** |
| Resolution | Deterministic by default; up to 20 short model-assisted reviews | Reserve **$0.10** |
| Strong synthesis | 12,000 input and 2,000 output tokens | At Sol example rates: **$0.044** |
| Verification/repair | One additional call of similar size only if validation fails | Reserve **$0.05** |
| API/source contingency | OpenAlex or replay overage, if any | Reserve **$1.00**; abort before unpriced broad replay |
| Total planned variable spend | Includes substantial contingency | **Below $2** expected; **$5 hard cap** |

The token arithmetic is intentionally transparent. If a selected model has different prices, replace only the rate table and recompute; the collection and token assumptions remain reviewable.

## Source/API costs

### OpenAlex

At the [audited OpenAlex API pricing](https://help.openalex.org/access/example-costs/):

- an API key receives a daily free budget;
- singleton entity retrieval is free;
- list/filter calls cost $0.10 per 1,000 calls;
- text and semantic search cost $1 per 1,000 calls;
- content downloads cost $10 per 1,000 files.

The first slice uses filters, identifiers, and metadata and should stay inside the daily free budget. It does not bulk-download content. Cache query pages and record the cursor so reruns do not repay discovery cost.

### Bluesky

Public AppView reads and public Jetstream v2 live endpoints have no published usage price in the audited documentation. Replay is API-key controlled and metered by compressed bytes, but no public dollar schedule was observed. Therefore:

- use AppView for a narrow historical seed;
- use server-side Jetstream filters for future records;
- do not budget or trigger broad replay without an explicit quote and byte cap;
- reconnect from the last durable cursor rather than replaying a large window.

### GitHub, Hacker News, RSS, and public web

The bounded official API/feed paths have no planned direct cash cost within published rate limits. They still incur rate-budget, caching, terms, and engineering costs. GitHub authentication may increase permitted rate limits but must not be used to collect outside the investigation scope.

X, LinkedIn, Reddit, YouTube, paid news APIs, proxy networks, and CAPTCHA services have a **$0 baseline allocation** because they are outside the first slice. Adding one requires a source-policy review and a revised cost model.

## Infrastructure costs

### Local development

| Resource | Expected cash cost |
|---|---:|
| PostgreSQL | $0 incremental |
| Application/API/worker | $0 incremental |
| Local raw text and indexes | Negligible at proof scale |
| Browser cluster, Redis, graph DB, vector DB | Not present |

### Small hosted proof

Planning range—not a provider quote:

| Resource | Monthly range | Scaling signal |
|---|---:|---|
| Managed PostgreSQL with backups | $15–$50 | storage, connections, backup retention, I/O |
| Small application/worker instance | $5–$25 | collection concurrency and API traffic |
| Object storage | $0 initially | add only after approved raw payloads exceed the DB threshold |
| Observability | $0 initially using structured logs/metrics | add a service only when retention/query needs justify it |
| Total | **$20–$75/month** | before production availability or traffic requirements |

The full vertical slice must deploy without Neo4j, Elasticsearch/OpenSearch, Redis, Kafka, a separate vector database, or Kubernetes. Each would add both a fixed bill and operational labor.

## Cost controls

### Before a call

- reject work without an investigation and source budget;
- estimate tokens from the actual span pack;
- reject a call that would exceed the run or investigation cap;
- use deterministic relevance filtering before model input;
- enforce maximum spans, characters, and documents per call;
- use the cheapest capability alias that passed the current evaluation.

### During processing

- key extraction cache on content hash plus span, ontology, prompt, schema, and model versions;
- batch compatible spans only when evidence IDs remain unambiguous;
- retry schema/transient failures at most once before review;
- never retry a semantic disagreement automatically;
- record predicted and actual tokens, latency, provider, and cost.

### After processing

- alert on cache-hit regression, tokens per accepted assertion, and cost per reviewed edge;
- halt a source when duplicate or irrelevant yield crosses its threshold;
- report spend by source, pipeline stage, model, investigation, and accepted assertion;
- require a written evaluation gate before enabling embeddings, browser crawling, or a new paid API.

## Primary efficiency metrics

Raw token cost alone can reward low-quality extraction. Track:

| Metric | Why it matters |
|---|---|
| dollars per accepted evidence-backed assertion | Connects spend to reusable knowledge |
| tokens per relevant document | Exposes prompt/span bloat |
| cache hit rate by stage | Confirms collect/normalize/extract-once behavior |
| duplicate-adjusted useful yield by source | Prevents paying for repeated content |
| evidence recall per retrieval token | Measures the small-subgraph strategy |
| dollars per investigation and repeat answer | Defines product economics |
| analyst minutes per accepted merge/assertion | Makes human review visible rather than pretending it is free |

Human review will likely be the dominant real cost. The correct optimization is not maximum automation; it is sending reviewers only ambiguous, high-value decisions with evidence and reasons.

## Sensitivity and breakpoints

| Change | Expected cost effect | Response |
|---|---|---|
| Corpus grows 10× but most pages are irrelevant | Small if deterministic filtering remains effective | Monitor relevant-yield rate; do not send all text to a model |
| Documents change frequently | Extraction cost only for new hashes/changed span packs | Preserve version and cache keys |
| Retrieval adds embeddings | One-time cost per new normalized text plus storage | Run only after the lexical recall gate fails |
| Browser fallback becomes common | Higher compute, failure, proxy, and maintenance cost | Reassess source value and consider a managed API rather than a browser fleet |
| Jetstream replay expands | Unbounded until byte price is known | Require quote, time/DID filters, and hard byte cap |
| Strong model packet grows | Linear token increase and weaker evidence discipline | Keep 12,000-token default; split investigations instead of expanding context |
| Historical outcome scoring is added | More data acquisition and review, not merely compute | Validate source availability before building predictive machinery |

## Budget gates

- A single extraction call estimated above $0.05 requires manual review of the span pack.
- A single synthesis call estimated above $0.25 is rejected unless the investigation owner raises the cap.
- The first investigation stops automatically at $5 in recorded model/API spend.
- A connector that yields fewer than 5 accepted assertions per 100 fetched records is paused for review.
- Any unpriced metered service is treated as unavailable for unattended use.
- Monthly infrastructure above $75 requires evidence that the proof workload cannot run on the baseline deployment.

## What this model excludes

- salaries and analyst review time;
- production high availability, enterprise security/compliance, and support;
- paid proprietary market datasets;
- full-text redistribution rights;
- global social-firehose retention;
- model training or fine-tuning;
- market-scale historical backtesting.

Those costs belong to later product decisions, not to proving whether the Memesis evidence method works.
