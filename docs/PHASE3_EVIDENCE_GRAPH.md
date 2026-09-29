# Phase 3 — Evidence to Memesis Graph

Status: implemented and locally verified on 2026-09-29.

This owner-requested phase spans the extraction and conservative-resolution work that the
original build plan listed separately. It stops at a provenance-backed graph and does not
implement influence scoring, ranking, or answer synthesis.

## Pipeline

```text
normalized Evidence
→ content-hash extraction cache
→ deterministic metadata, entity, time, event, and proposition extraction
→ exact immutable EvidenceSpan
→ conservative entity and belief resolution
→ typed Assertion with extractor lineage
→ ontology-validated, provenance-backed graph edge
```

Deterministic extraction rejects questions, topic fragments, boilerplate, UI instructions,
markdown links, off-domain statements, and event-only announcements as beliefs. Beliefs
retain proposition, stance, scope, modality, and horizon. Events remain events.

## Resolution rules

- Exact source-scoped stable identifiers can auto-link.
- Names and aliases alone never auto-merge.
- Same-name candidates remain separate unless evidence supplies a stable identifier or a
  reviewer records a merge.
- Beliefs can reuse an exact structural signature or a very-high-overlap proposition only
  when scope, modality, and horizon also match.
- Aliases, external identifiers, confidence, supporting evidence, and reviewed merge
  decisions are durable records.

## Model boundary

`StructuredExtractionModel` is provider-neutral. The pipeline sends only unresolved spans
to the cheap extraction model in bounded packs. An optional stronger ambiguity model sees
only spans the cheap model still marks unresolved. Every model-derived assertion requires
confidence, model, prompt version, schema version, exact evidence spans, and token counts.
Model proposals cannot authorize entity merges.

## Verification

- Automated tests: 25 passed.
- Frozen manually inspectable dataset: 30 examples.
- Fixture entity extraction: precision 1.00, recall 1.00, F1 1.00.
- Fixture belief extraction: precision 1.00, recall 1.00, F1 1.00.
- Fixture relationship extraction: precision 1.00, recall 1.00, F1 1.00.
- Resolution checks: 3/3, including supported `Sam Altman`/`sama`/`@sama`/`OpenAI CEO`
  resolution and a deliberate `Alex Smith` same-name non-merge.
- Fixture model usage: zero actual tokens; one ambiguous item representing approximately
  25 fallback input tokens (0.83 per evidence item) if a provider is configured.
- Live Phase 2 ledger: 11 evidence records → 21 nodes, 10 edges, 4 beliefs, 11 evidence
  projection checkpoints, no failures, and zero model calls. A repeat pass produced 11
  extraction-cache hits and no writes.

These fixture scores measure the frozen examples, not open-world recall. Ambiguous live
spans remain explicitly unprojected unless a configured model or reviewer resolves them.
