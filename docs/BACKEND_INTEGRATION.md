# Backend integration, 2026-09-30

The active checkout merges upstream `49fe283` (Phase 9) with the local evidence
auditing and market/date scoping work. The old working state is recoverable from
the Git branch `recovery/pre-phase9-integration`; there is no second active codebase.

## Preserved local features

- Citation validity, semantic support, and exploratory hypotheses remain distinct.
- Optional OpenAI-compatible claim support verification remains available.
- Workspace, Ask, full-context retrieval, and scoring share market/date boundaries.
- Published-time and known-time cutoffs remain separate and explicitly reported.
- Scope membership follows supported graph paths, including adjacent markets,
  without requiring literal query keyword matches.
- Empty or poorly connected markets never silently fall back to the global corpus.

## Imported upstream features

- Phase 9 ingestion and evaluation scripts, reports, and evaluation fixtures.
- Perception schema, storage, and extraction.
- TypeSafe/OpenRouter Jev client, hybrid routing, and offline fallback.
- Updated web collector and historical filtering work.
- The Phase 9 bundled database: 1,091 evidence records, 2,480 nodes, 1,553 edges.

The upstream corpus includes 753 Hacker News, 144 Bluesky, 163 OpenAlex,
27 fixture, and four evaluation-supplement evidence records.

## Preview

Start the backend from the repository root with
`MEMESIS_DATABASE_URL=sqlite:///./memesis-phase5.sqlite3` and
`python -m uvicorn memesis.app:app --host 127.0.0.1 --port 8000`.
Start the frontend from `frontend` with
`npm run dev -- --hostname 127.0.0.1 --port 3000`.

Health: http://127.0.0.1:8000/healthz
API documentation: http://127.0.0.1:8000/docs
Interface: http://127.0.0.1:3000/

## Remaining limitations

Most collected records have no supported connection to the three seeded market
nodes. Market views remain sparse despite the larger database. Establishing those
connections requires further evidence extraction and review, not global fallback.
Serving the preview does not schedule ingestion. Provider keys are required for
live Jev use; the offline fallback remains a simulation.

No changes were pushed to the upstream repository or the user's fork.
