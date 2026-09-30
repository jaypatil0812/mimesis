# Evidence-dependent answers

The answer pipeline now has three explicit execution modes:

1. **Deterministic:** direct retrieval, actor scores, company records, perceptions,
   temporal records and counterevidence are formatted from the scoped packet.
   No strategic conclusions are invented by a local template.
2. **Strategic reasoning:** a configured OpenAI-compatible chat endpoint receives
   the same scoped evidence, typed memory observations, graph relationships,
   scores, dates, opposing assertions and coverage limitations. Its JSON response
   must pass schema and reference checks.
3. **Visible fallback:** unconfigured providers, HTTP failures, invalid responses
   and excessive input budgets return recorded evidence plus a fallback status.

## Configure

In the local, ignored `.env`, set:

```dotenv
MEMESIS_MODEL_API_BASE_URL=https://your-provider.example/v1
MEMESIS_MODEL_API_KEY=your-local-secret
MEMESIS_REASON_STRONG_MODEL=your-provider-model-name
MEMESIS_REASONING_TIMEOUT_SECONDS=60
MEMESIS_REASONING_MAX_PACKET_TOKENS=24000
```

The provider must support `/chat/completions`, JSON object responses and the
configured model. Restart the API after changing environment settings. The input
budget is an approximate packet-token limit; it excludes schema/system overhead.
Oversized packets produce `PACKET_TOO_LARGE`; the adapter does not silently remove
evidence to fit. No provider calls are made until both key and model are configured.
The configured endpoint receives source passages and client context.

Optional `MEMESIS_VERIFY_CLAIM_SUPPORT=true` enables the existing separate advisory
source-support check. This adds another model call and does not establish truth.

## Traces and uncertainty

Each strategic conclusion carries `evidence_ids`, `observation_ids`, its epistemic
status and a `reasoning` explanation. Source identifiers must exist in the supplied
packet. Observation premises expand to their supporting evidence. Proposed records
cannot be promoted to observed conclusions. Accepted interpretations remain
interpretations. Uncited exploratory connections are allowed as **SPECULATIVE**;
the prompt requires explicit missing premises and a way to investigate them.

These checks validate structure and provenance, not semantic entailment. A model
can still misread a passage, ignore a qualification or invent reasoning around a
valid citation. Human review and adversarial semantic evaluation remain necessary.
Curated historical analogues are identified as unsourced templates in the prompt;
they are not silently copied into the answer as established precedents.

Market motion now describes measured belief-discussion velocity. Missing metrics
are unknown, confidence is nullable, and mixed velocity directions are uncertain.
It does not invent commercial acceleration, market adoption, customer pain or
adjacent-market winners. Event counts have no acceleration meaning without a rate
baseline. Temporal answers show dated records and disclose that a baseline delta
has not been established.

## API and preview

`POST /api/markets/{market_id}/ask` exposes `fallback_status`,
`reasoning_execution`, `market_motion`, claim traces and `unknown_or_missing`.
The existing answer panel displays execution mode, fallback reason and each claim's
reasoning. Market/date boundaries remain enforced for both compact and full context.
Review candidates and graph paths remain available; no new literal-keyword gate
was added to reasoning.

Usage records count provider-reported tokens, rather than fictitious packet-plus-500
tokens. Missing provider usage is marked unavailable. Cost is still an illustrative
estimate at the old benchmark rate, not a provider invoice. The evaluation report
now says `COMPLETED`, rather than declaring semantic quality or real cost savings
when no model ran.

## Before and after

| Situation | Before | After |
| --- | --- | --- |
| No velocity or confidence metrics | Positive defaults and an AI-market narrative | Unknown indicators; `UNCERTAIN`; missing coverage |
| Company events absent | Named model launches could appear anyway | Retrieved company records/candidates only, with review status |
| Workload passage changes from cheaper to more expensive | Fixed strategic conclusion could retain its story | Direct passage changes; strategic adapter receives the changed evidence |
| Provider missing or fails | Silent deterministic strategic narrative; invented model tokens | Visible evidence-only fallback; no fabricated usage |
| Uncertain graph connection | May appear alongside fixed recommendations | Available to reasoning as a labelled candidate or speculative hypothesis |

`tests/test_evidence_reasoning.py` checks changed and contradictory inputs,
candidate promotion, malformed JSON, invalid citations, provider timeouts, missing
configuration, input limits and exploratory hypotheses. HTTP responses in these
checks are simulated. They demonstrate routing and validation, not live model
understanding or semantic quality. A live counterfactual evaluation still needs a
configured model and review of the resulting conclusions.

The database counterfactual test appends a contradictory workload report to an
isolated ledger. The current answer gains the new report, while a query at the
earlier cutoff retains its original answer. Original source evidence stays intact.
Confidence also no longer assumes 95% temporal consistency or a positive
counterevidence balance. It calculates date completeness/coherence and retrieved
opposing assertions. Distinct actor names do not establish reporting independence;
that component requires explicit `independence_verified` evidence metadata.
