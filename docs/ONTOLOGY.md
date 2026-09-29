# Memesis Ontology

Status: v0 contract for the first vertical slice  
Ontology version: `memesis-0.1`  
Scope: AI infrastructure and the shift toward smaller or specialized models

## Purpose

The ontology represents evidence-backed claims about how people express beliefs, how content carries and amplifies those beliefs, how companies act, and what happens afterward. It is deliberately small. It is not a universal knowledge graph, a social graph, or a truth database.

Every graph element is a view over an assertion and its evidence. A node or edge without provenance may exist as a draft candidate, but it cannot participate in a published conclusion or score.

## Node types

| Node | Definition | Stable identity | Required fields | Important exclusions |
|---|---|---|---|---|
| `Person` | A natural person acting publicly in the investigated market | Verified source identifiers such as DID, ORCID, OpenAlex author ID, GitHub user ID, or canonical profile URL | canonical name, at least one source-scoped identifier, resolution state | A name mention alone is not a resolved person |
| `Company` | A commercial company, nonprofit, lab, or institution that acts as an organization | Canonical domain plus official IDs where available | canonical name, organization kind, domain/identifier, resolution state | Informal communities and product brands without an accountable organization |
| `Belief` | One normalized, falsifiable or at least contestable proposition with explicit scope, modality, and time horizon | Memesis ID; equivalence is adjudicated, not source-defined | proposition, subject, scope, modality, horizon, resolution state | Topics, slogans, sentiment, and private mental states inferred from behavior alone |
| `Market` | A demand/supply arena in which products or capabilities compete or transact | Reviewed Memesis taxonomy ID | canonical label, boundary definition, inclusion/exclusion criteria | A broad topic with no defined buyer, supplier, or exchange boundary |
| `Product` | A named product, model, service, or technical offering | Official product URL/repository/model ID plus owner | canonical name, product kind, owner candidate, identifier | A generic technology category; use Market or Belief as appropriate |
| `Content` | A particular version of a public communicative artifact | Source plus external ID and version/hash | canonical URL/URI, source, published/observed time, document-version ID | The mutable latest state without version identity |
| `Event` | A bounded occurrence used to represent company action, market signal, or observed outcome | Memesis ID plus event fingerprint | subtype, description, occurrence interval, evidence | A vague continuing state or an unevidenced causal interpretation |

## Why one additional edge is necessary

The requested edge set contains `Event` as a node but no edge that connects an event to its participants. Memesis therefore adds exactly one edge: `PARTICIPATED_IN`. Without it, a launch, pricing change, benchmark, acquisition, deployment, or observed outcome would be an orphan and `ACTS_ON` could not be grounded in an observable event.

No other node or edge type is added for the proof.

## Edge contracts

| Edge | Allowed source → target | Meaning | Minimum evidence rule |
|---|---|---|---|
| `BELIEVES` | Person → Belief | The person explicitly endorses the proposition in the applicable interval | Attributable first-person statement or reviewed explicit attribution; behavior alone is insufficient |
| `PUBLISHED` | Person/Company → Content | The actor authored or issued the specific content version | Source author/publisher metadata or official page/account |
| `EXPRESSES` | Content → Belief | The content states, supports, opposes, qualifies, or mentions the belief | Exact span plus stance; `mentions` is not endorsement |
| `INFLUENCES` | Person/Content/Belief → Person/Belief/Company/Event | A source explicitly attributes influence, or a versioned derived rule reports a bounded influence signal | Must be marked `asserted` or `derived`; derived edges include inputs and algorithm version |
| `FOUNDED` | Person → Company | The person founded or co-founded the company | Official biography, filing, or high-quality secondary source |
| `WORKS_AT` | Person → Company | The person has an employment/leadership affiliation during an interval | Dated official profile or equivalent source; always time-bounded when known |
| `INVESTED_IN` | Person/Company → Company/Product | The actor made a financial investment | Announcement, filing, fund record, or attributed report; advice/support alone is insufficient |
| `ACTS_ON` | Company → Belief | An observable company event is consistent with and specifically linked to a belief | At least one qualifying Event connected to the company plus evidence linking action to proposition; rhetoric alone is insufficient |
| `BUILDS` | Company → Product | The company develops or operates the product | Official product/repository/model documentation |
| `SERVES` | Product/Company → Market | The offering or company targets a defined market | Product positioning, customers, use cases, or reviewed market mapping |
| `ADJACENT_TO` | Market → Market | Markets share a documented buyer, supplier, capability, or substitution path | Symmetric projection with adjacency basis and evidence; topical similarity alone is insufficient |
| `DEPENDS_ON` | Product/Company/Market → Product/Company/Market | The source requires the target as a technical, supply, distribution, or economic dependency | Dependency type and evidence required; correlation is insufficient |
| `PRECEDES` | Belief/Content/Event → Belief/Content/Event | The source occurrence ends or begins before the target occurrence under a stated clock | Deterministic temporal comparison; never implies causality |
| `AMPLIFIES` | Person/Company/Content → Content/Belief | The actor or content redistributes or materially increases exposure to existing content/belief | Repost/quote/link/reference or reviewed high-similarity propagation evidence |
| `PARTICIPATED_IN` | Person/Company/Product/Market → Event | The entity was an actor, object, venue, or measured market in the event | Role field plus event evidence |

### Direction and inverses

Edges are stored once in the canonical direction above. The API may expose computed inverse labels such as “has employee,” but it does not persist inverse duplicates. `ADJACENT_TO` is semantically symmetric; the database stores a canonical ordered pair and the query layer expands both directions.

## Common edge fields

Every active edge has:

```text
edge_id
edge_type
from_node_id
to_node_id
qualifiers_json        constrained per edge type
valid_from?            when the asserted relation became true
valid_to?              when it ceased to be true
observed_at             when Memesis first observed its evidence
recorded_from           transaction-time start
recorded_to?            supersession/tombstone time
assertion_method        source_explicit | extracted | deterministic | analyst | derived
confidence              calibrated confidence in extraction/linking, not truth
review_state            proposed | accepted | rejected | superseded
ontology_version
derivation_version?
```

Evidence is many-to-many through `edge_evidence(edge_id, evidence_span_id, role)`, where `role` is `supports`, `contradicts`, or `qualifies`.

## Evidence and assertion model

An evidence span is an immutable coordinate into one normalized document version:

```text
document_version_id
normalizer_version
start_offset
end_offset
exact_text
content_hash
```

An assertion is the interpretive unit between evidence and graph. It records subject, predicate, object/value, stance, modality, confidence, extractor/prompt/schema version, validation results, and review state. Several assertions may support one canonical edge; one assertion may be rejected without erasing its source.

Model confidence means “the extraction/link is likely faithful to the cited span.” It does not mean “the belief is likely true.”

## Belief contract

A Belief is an atomic proposition, not a theme. The normalization template is:

```text
subject + predicate + object/outcome
scope: market/geography/population
modality: observed | predicted | normative | causal-claim
time horizon: historical interval | current | explicit future interval
conditions/qualifiers
```

Example:

> For routine enterprise inference workloads, task-specialized models will gain deployment share relative to frontier general-purpose models during 2025–2027 because their cost and latency are lower.

This must not be collapsed with:

- “small models are interesting” — not an atomic proposition;
- “all frontier models will disappear” — different scope and strength;
- “we launched a small model” — an Event/company action, not by itself a belief;
- “small models are cheaper” — a narrower supporting belief.

### Belief stance

Stance is stored on the `EXPRESSES` assertion:

- `supports`: presents the proposition as true or likely;
- `opposes`: presents its negation as true or likely;
- `qualifies`: restricts conditions, scope, or confidence;
- `mentions`: discusses without taking a position.

Only reviewed `supports`/`opposes`/`qualifies` evidence can contribute to belief-position or influence scores. `mentions` contributes only to discovery.

## Event subtypes

Subtypes are controlled values, not new node types:

- `product_launch`
- `model_release`
- `pricing_change`
- `investment`
- `acquisition`
- `partnership`
- `deployment`
- `benchmark_result`
- `hiring_or_reorganization`
- `policy_or_standard`
- `market_measurement`
- `observed_outcome`

Add a subtype only when an encountered event cannot be represented faithfully. A subtype does not create a causal conclusion.

## Temporal rules

Memesis preserves three clocks:

1. **Occurrence/publication time:** when content was published or an event happened.
2. **Observation time:** when the system collected the evidence.
3. **Record time:** when an assertion or resolution decision entered or left the canonical graph.

Valid intervals may be uncertain. Store earliest/latest bounds and precision rather than inventing a day. A later source can correct an event date by superseding an assertion; it never mutates the old record.

`PRECEDES` is materialized only between selected analytically important nodes, not between every time-sortable pair. It includes clock type and minimum/maximum lag. It is necessary but never sufficient evidence for causal influence.

## Identity and merge rules

- External identifiers are source-scoped and unique.
- Exact stable identifiers may auto-resolve; names alone may not.
- A company rebrand can be an alias; a merger or successor is not an automatic identity merge.
- Employment affiliation is time-varying and cannot be used as a permanent identity property.
- Belief equivalence requires matching proposition, scope, modality, and horizon.
- Every merge is reversible through a merge ledger; source records keep their original candidate IDs.
- A model may propose merge candidates but cannot make the final merge decision.

## Vertical-slice graph example

```text
Person ─PUBLISHED→ Content ─EXPRESSES(supports)→ Belief
   │                    │                           │
WORKS_AT             AMPLIFIES                  PRECEDES
   │                    │                           │
Company ───────────ACTS_ON─────────────────────────┘
   │                    │
 BUILDS          PARTICIPATED_IN
   │                    │
Product ─SERVES→ Market ←PARTICIPATED_IN─ Event
                       │
                 ADJACENT_TO
                       │
                    Market
```

The `ACTS_ON` edge is accepted only when the Company also participates in a concrete action Event and evidence links that action to the Belief. The graph can show temporal sequence and attributable statements, while the answer must still distinguish observation from causal inference.

## Validation invariants

An assertion cannot become active if:

- any endpoint violates the edge contract;
- its evidence span is missing or does not exactly match the stored normalized version;
- the source document is outside the investigation's approved source policy;
- publication/validity bounds are incoherent;
- a `BELIEVES` edge rests only on inferred behavior;
- an `ACTS_ON` edge lacks a connected qualifying Event;
- an `INFLUENCES` edge lacks either explicit attribution or a reproducible derivation record;
- an `ADJACENT_TO` edge has no named adjacency basis;
- an extracted identity was auto-merged on name similarity alone;
- the source is tombstoned and the policy disallows continued active use.

## Ontology change process

Ontology changes require:

1. a real source example that cannot be represented;
2. the proposed node/edge/property and why qualifiers or Event subtypes are insufficient;
3. migration and backward-compatibility impact;
4. updated endpoint and validation tests;
5. review of score and retrieval behavior;
6. a new ontology version and re-projection plan.

The default answer to a new type is “not yet.”
