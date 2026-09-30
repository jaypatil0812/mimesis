# Mimesis implementation guidance

This workspace combines upstream Phase 9 with evidence auditing and market/date
scoping. README.md describes the product; docs/MARKET_SCOPING.md describes query
boundaries. Do not use the former Phase 4 implementation reference as current status.

## Invariants

- Preserve immutable raw documents, versions, evidence, and exact source spans.
- Every graph node and edge must carry supporting evidence provenance.
- Deduplicate processing by content hash and extractor/model version.
- Resolve people by stable identifiers; names alone do not establish identity.
- Model extraction is a proposal subject to schema, ontology, span, and provenance
  validation. Keep uncertain assertions distinguishable from accepted relations.
- Market/date scope applies to retrieval, scores, full-context answers, and API
  workspaces. Do not silently fall back to global evidence for empty markets.
- Historical calculations use explicit cutoffs. Keep publication time distinct
  from when the system knew a record; expose historical metadata limitations.
- Preserve supported graph paths and exploratory hypotheses without requiring
  literal query keyword matches. Citation integrity does not prove semantic support.
- Scores summarize observed evidence; they are not proof of causation or prediction.
- Missing evidence is a visible coverage gap. Popularity is not influence.
- Keep secrets out of version control. Provider simulations are not live model calls.
- Serving the API/UI does not start continuous collection.

## Development

- Use apply_patch for source edits and avoid destructive repository resets.
- Python package: src/memesis; frontend: frontend; migrations: migrations/versions.
- SQLite supports the local preview; PostgreSQL remains the configured default.
- The preview explicitly uses sqlite:///./memesis-phase5.sqlite3.
- Work against the user's fork; do not push changes to vdnthtml/mimesis.
