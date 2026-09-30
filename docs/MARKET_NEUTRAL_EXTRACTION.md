# Market-neutral extraction and controlled memory rebuild

Extraction recognises source observations before market assignment. No AI keyword
is required. Market retrieval boundaries remain evidence-backed graph paths; a
document is not assigned to a market simply because it contains a topic name.

## Meaning and uncertainty

- Rules retain exact propositions and reporting prefixes, including quotations,
  criticism, negation and conditions. EXPRESSES means the source expresses the
  proposition, not that the proposition is a verified fact.
- Generic observations remain proposed. Explicit contrasts can produce separate
  exact clause spans with the complete sentence in `context.source_statement`
  and original `source_start`/`source_end`. An omitted subject is flagged as
  ellipsis; it is never invented in the quotation. Shared scope requires review.
- Observed changes, complex conditions, quoted claims and unresolved sentences
  are routed to the optional structured extraction adapter. Prompts work across
  markets and preserve shared conditions. Model output remains proposed after
  schema, span and provenance validation.
- Without a configured adapter, `unresolved_without_model` reports the remaining
  semantic work. Rules do not claim general language understanding.

The battery example retains both “Recycling costs declined for nickel-rich
batteries” and “did not decline for lithium-iron-phosphate batteries in the same
pilot.” Both point to the complete source sentence. The second clause's omitted
subject and the shared pilot scope are explicit review requirements.

## Rebuild existing evidence

Pause the collection worker, then run a bounded batch:

```powershell
.\.venv\Scripts\python.exe -m memesis.cli --database-url sqlite:///./memesis-phase5.sqlite3 rebuild-memory --limit 100 --output artifacts/intelligence-evaluation/rebuild-001.json
```

Use repeated `--evidence-id UUID` flags to target records, or a larger limit to
cover the entire preserved corpus. Re-running the same extractor, interpretation
and model/prompt versions reuses existing projections. Choose a new output path
for each immutable receipt. `--version` changes interpretation lineage; the
default matches the worker's `memory-worker-v1` interpretation.

By default this maintenance command is offline. `--with-models` explicitly enables
configured extraction calls and requires both `MEMESIS_MODEL_API_KEY` and
`MEMESIS_EXTRACT_SMALL_MODEL`. The provider base URL uses
`MEMESIS_MODEL_API_BASE_URL`. Keep keys in local configuration, never Git.
Strategic reasoning is a separate configuration and is not enabled by a rebuild.

For every document, extraction, comparison, projection retraction and receipt
are committed together. A failure rolls back that document. Previous source
documents, versions, evidence and spans are retained. No recollection is needed.

The comparison distinguishes:

| Result | Handling |
| --- | --- |
| Same source proposition/relationship | Retain existing assertion; retire duplicate new projection |
| New supported interpretation | Add versioned assertion; uncertain observations stay proposed |
| Obsolete generated interpretation | Supersede assertion and retract its owned graph edges |
| Human-reviewed interpretation | Preserve and flag in `protected_assertions` for review |
| Earlier model interpretation without re-execution | Preserve and flag; an offline run cannot invalidate it |
| Missing normalization or processing failure | Keep previous memory; record failure and rollback |

Receipts store assertion IDs and processing counts. Preserved assertion/span
records provide the exact before/after text. Graph revisions keep previous
assertion/node/edge payloads, while the current graph omits retired projections.
This is an audit trail, **not complete reconstruction of every historical graph**.

The worker uses this same rebuild mechanism when processing evidence. An
extractor-version change queues previously tracked records in bounded batches.
The maintenance command queues affected investigations using tracked evidence
and saved snapshots, without rewriting their earlier conclusions. Enabled watches
are re-analysed by the worker; disabled watches require an explicit run.

## Evaluation

The adversarial corpus includes the original battery example. Passing its exact
proposition check only establishes retention, not semantic truth or human review.
Dedicated regressions cover shared context, reporting attribution, idempotency,
transaction rollback, obsolete edge retraction and protected human reviews.

Review source independence, conditions and semantic support before treating a
pattern as decision evidence. Neither broader extraction nor a successful rebuild
establishes that the system has predicted the next major market.
