# Connected market memory

This implementation extends the existing assertion and evidence-span ledger. It
does not introduce a second graph database or require another service.

## Observations and interpretation

Each `MEMORY_OBSERVATION` assertion retains its exact normalized source span,
subject, optional target, observation type, attribution mode, meaning features,
source family, extractor/model lineage and review history.

Types: attributed claim, company statement, company action, customer experience,
relationship, interpretation, identity link, and belief equivalence.

All new memory observations start as `proposed`. An interpretation remains
`inferred` after review. Accepting a reported observation means a reviewer approved
the extraction; it does not establish that a speaker's statement is true.
Interpretations require `context.hypothesis`; optional
`context.supporting_observation_ids` must reference real, unretracted observations.
Their source evidence and spans are retained together. The operator API reports
whether those premises remain candidates, are reviewed, or have been challenged.

The deterministic sentence extractor proposes generic claims, actions and
first-person experience without an AI-market vocabulary gate. Company attribution,
nuanced classification, and difficult relationships may require the structured
extraction model or an analyst. Those are reviewable proposals, not guaranteed
automatic semantic understanding.

## Identity and belief resolution

- Stable identifiers must agree with entity type; names alone never auto-merge.
- Opaque identifier normalization preserves case, punctuation, and words such as
  `ceo` and `cto`; name/title normalization is never applied to identity keys.
  Exact raw-value lookup reads legacy rows without repeating lossy normalization.
- Reviewed identity links redirect future resolution while preserving historical
  IDs and evidence. `SAME_ENTITY` records the supported connection. Rejecting a
  review retracts its graph edge and future redirect; old data is not rewritten.
- Only exact, versioned belief signatures merge automatically.
- Word overlap can propose equivalence but cannot prove it. Meaning features
  preserve negation, qualification, conditions, and time expressions.
- Approved `EQUIVALENT_TO` links connect beliefs without destructively merging
  their original propositions. This also allows graph exploration.
- Quotation and criticism cannot create an automatic author `BELIEVES` edge.
- Model-proposed identifiers must occur in their supporting entity span; invented
  identifiers are removed. Model confidence alone never approves graph relations.

Meaning features are conservative rules. Exact source text remains authoritative;
these rules are not a complete linguistic parser or a calibrated truth model.

## Source families

Exact normalized copies share a family. Explicit `original_source_url`,
`syndicated_from`, or `repost_of` metadata connects known copies to a stored
original. Differently worded copies without derivation metadata remain unresolved;
similarity does not establish common origin. Source-family scoring uses the derived
family where present and keeps its legacy fallback otherwise. A source family is
not proof of independent authorship or community representation.

## Market relationships and review

An explicit sentence naming a known company/product and market with service
language can propose `SERVES`. Structured extraction or an analyst can also
propose supported relationships and attach use-case context. Mere topic mentions
never assign all evidence to a market.

Review, promotion and retraction are transactional. Only approved connections
enter the active graph. Candidate observations remain available separately, so
novel possible connections can be investigated without masquerading as facts.

## API

- `GET /api/memory/observations?review_state=proposed&limit=100`
- Optional `entity_id`, `offset`, and `limit` support investigation and pagination.
- `POST /api/memory/observations` proposes an observation using existing
  `evidence_id`, `subject_id`, optional `target_id`, `observation_type`, exact
  normalized-text `start`/`end`, and `context`.
- A relationship requires `context.edge_type`, optionally `context.qualifiers`.
- `POST /api/memory/observations/{id}/review` accepts `state`, `reviewer`, `note`.
- States: `proposed`, `accepted`, `rejected`, `superseded`.

The API is a local operator interface. Production authentication/authorization is
not introduced by this change.

Scoped reasoning packets include up to 40 memory observations supported by their
retained evidence. Proposed records are labelled explicitly; rejected/superseded
records are excluded. The existing strategic synthesizer still has template
limitations; improving strategic reasoning is a separate development area.

## Existing corpus and reproducible examples

`MEMESIS_DATABASE_URL=sqlite:///./memesis-phase5.sqlite3` with
`python scripts/backfill_connected_memory.py` adds candidates to existing stored
documents and annotates existing edge families. It preserves raw evidence and
does not approve or reconstruct legacy semantic relationships. Re-running it
reuses stable observation IDs. Legacy edges have not become manually verified
merely because a backfill ran; review existing relationships separately.

Run `python scripts/demo_connected_memory.py` for synthetic before/after examples
against baseline commit `41386f1`. It uses isolated in-memory SQLite and no provider
calls. Results are saved to `data/examples/connected_memory_before_after.json`.
The examples demonstrate negation separation, quote attribution, observation
types, conditions, explicit syndication, review/promotion/retraction, identity
corroboration, and idempotence. They do not benchmark real-world extraction quality.
