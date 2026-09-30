# Continuous, bounded investigations

An investigation connects collected observations through typed graph paths,
proposes explanations, retains alternatives and gaps, and performs a limited
follow-up search. Its hypotheses never become graph facts through this workflow.

## Before and after

Previously, collection and extraction were separate manual operations. A graph
connection did not have a durable investigation, a next question, or an update
history. Now a configurable watch owns a schedule, source checkpoints, extraction
backlog, versioned snapshots, review history and bounded follow-up cycle.

For example, a company pricing statement and a customer cost experience can
produce a **comparison to investigate** when a supported path connects them.
The result retains both observations, the exact edge IDs, workload-comparability
gaps, shared-source alternatives and a next question. It does not infer that the
company misled customers merely because the records are connected.

## Run locally

The API and UI do not start collection. Run exactly one separate worker:

```powershell
.venv\Scripts\python.exe -m memesis.cli --database-url sqlite:///./memesis-phase5.sqlite3 db-upgrade
.venv\Scripts\python.exe -m memesis.cli --database-url sqlite:///./memesis-phase5.sqlite3 watch-create data/watchlists/ai-inference-research.json
.venv\Scripts\python.exe -m memesis.cli --database-url sqlite:///./memesis-phase5.sqlite3 worker --poll-seconds 30
```

The example is disabled by default. Enable it through the configuration API or
queue a single bounded tick with `POST /api/investigations/{id}/run`. A disabled
watch does not automatically continue subsequent pages after that manual tick.
`worker --once` processes due work then exits. Each tick handles at most eight
watches, oldest due first. A singleton lease, heartbeat and fenced checkpoint/
snapshot writes prevent overlapping workers from advancing durable state.

This is a local process, not an installed Windows startup service. Closing it or
restarting the computer stops collection. A web server running is not evidence
that the worker is running. Worker health distinguishes recent heartbeats from
an active lease; idle workers release the lease between polling ticks.

## Configure and inspect

Use the API's Swagger page at `http://127.0.0.1:8000/docs`:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/investigations` | Watches, collection health and worker heartbeat |
| `POST /api/investigations` | Create a watch using InvestigationConfig |
| `GET /api/investigations/{id}` | Snapshot history, runs, reviews and coverage |
| `PUT /api/investigations/{id}` | Update config with expected_revision |
| `POST /api/investigations/{id}/run` | Queue work for the separate worker |
| `POST /api/investigations/{id}/patterns/{pattern_id}/review` | Append proposed/reviewed/rejected feedback |
| `GET /api/markets/{market_id}/investigations` | Watches explicitly scoped to that market |

Reviewing a pattern does not promote its relationships to facts. Source and span
checks validate provenance, not whether an explanation is semantically correct.
There is no new investigation panel in the frontend yet.

The config controls source/query allowlists, lookback, interval, graph hops,
pages per source, evidence per tick, number of patterns and follow-up rounds.
Supported scheduled adapters are Hacker News, Bluesky AppView, OpenAlex, RSS
and public GitHub issue/PR search. GitHub requires a `repo:owner/name` query
boundary. Its adapter retains title/body, repository and numeric author IDs,
creation/update timestamps and original JSON. It does not collect comment
threads or releases. GitHub search caps/incomplete responses are coverage
failures and cannot advance a completed checkpoint.
This does not start a Bluesky Jetstream streaming consumer.

## Discovery and scope

Source-backed research starts from the latest collected evidence roots and
follows typed links within the configured hop budget. It has no AI keyword
whitelist. Related records may enter through supported paths even if their text
does not contain the query words. Retrieval still has a size budget; omissions
and older roots excluded by that budget are reported.

Market and date boundaries apply before this exploration. A market-scoped watch
cannot import unrelated global evidence when its market is empty. Collection
does not automatically assign search results to a market. A watch without a
market ID is explicitly source-rooted research, not proof of market coverage.
A watch without sources analyzes the stored scoped graph.

## Explanations and memory

Each pattern retains supporting observations and evidence IDs, connecting edge
paths, alternative explanations, contradictory/related opposing evidence,
missing premises and the next investigation. Snapshot history records evidence
added or removed from scope. Prior hypotheses whose supporting evidence remains
in scope are supplied to the reasoning model for reconsideration.

Configure the reasoning provider as described in EVIDENCE_REASONING.md. Without
a key and reasoning model, only structural comparisons, stored sequences and
recurring perception candidates are produced, with `not_configured` status.
These are speculative leads; they do not establish the five substantive pattern
categories automatically. A successful model can return no patterns. Provider
failure or invalid references retain a visible structural fallback.

Optional configured extraction/resolution models are used by the worker;
otherwise extraction is deterministic. Model proposals remain subject to the
existing schema, ontology, span and provenance checks. Source-family counts
are displayed but do not certify independent evidence.

## Continuous processing and limitations

- Raw documents, versions and evidence are preserved. Page receipts are durable
  before checkpoint advancement. An interrupted worker recovers their evidence
  IDs into its processing queue.
- An incomplete scan retains a continuation cursor and leaves its completed
  checkpoint unchanged. Page budgets cause another scheduled tick rather than
  pretending collection finished. RSS pages use a frozen feed snapshot; feeds
  are revisited to catch edits, but vanished historical entries are unavailable.
- Content hashes and extractor/interpretation versions control reuse. Changing
  `processing_version` queues tracked evidence for a controlled rebuild. Previous
  accepted assertions remain preserved: obsolete projections need review, and
  the run explicitly flags that requirement. This is not automatic retraction.
- Source and job failures have retries and visible receipts. Extraction failures
  become visible dead letters after three attempts; a processing-version change
  resets their attempts. Backlog pressure defers additional primary collection.
- Analysis runs when the scoped evidence/interpretation fingerprint changes.
  Unchanged snapshots are reused; failed reasoning is retried.
- Follow-ups use configured sources only. Their rounds are finite and follow-up
  evidence cannot reset its own budget. If a follow-up reaches its round limit
  before completing pagination, its checkpoint stays pending; another primary
  evidence cycle or analyst configuration is required to revisit it.
- Last completed search, pagination state, failures, coverage notes and collection
  lag are visible together. Search indexes can omit or cap records. A successful
  HTTP request or a fresh timestamp does not establish exhaustive coverage.

Semantic hypothesis quality still needs analyst review and evaluation with
contradictory evidence. Production deployment additionally needs authentication,
an operational service manager, source-specific rate/billing monitoring and
validation against real PostgreSQL and configured reasoning providers.
