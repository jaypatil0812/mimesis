# Phase 4 — Deterministic v0 scores

Status: implemented 2026-09-29  
Version: `deterministic-v0.1`

These scores rank observed graph patterns. They are not truth, proof of causality, a
market forecast, or a model's opinion. The scoring package imports no model gateway and
reports zero LLM calls.

Every score is stored with:

- subject and optional belief context;
- `as_of` cutoff and any comparison window;
- exact formula and algorithm version;
- component values, weights, point contributions, raw numerators/denominators, and
  supporting evidence IDs;
- the graph-edge inputs, evidence coverage, and explicit gaps;
- a SHA-256 input fingerprint, making a replay of the same snapshot idempotent.

All terms are on a 0–100 scale. `sat(n, k) = 100 × min(n/k, 1)`. Scores are weighted
sums; missing evidence normally yields zero for the affected component and a visible
coverage gap. Components are not silently reweighted.

## Historical and independence rules

Only edges whose effective time is at or before `as_of` are visible. Effective time is,
in order: `valid_from`, source `published_at`, then `retrieved_at` as a labeled fallback.
Velocity compares the current window with the immediately preceding equal-length window.

An independent actor group is the actor's explicit `WORKS_AT` company at the observation
time, the company itself, or the actor when no organization is known. Two employees of
the same known company are one group. This is deliberately conservative; it does not
claim that all unaffiliated accounts are truly independent.

V0 does not invent an actor-quality or reputation rating. Because the current graph has
no reviewed historical-quality field, independent groups count equally and evidence
auditability is reported separately. A later version may add a deterministic track-record
term only after reviewed historical outcomes exist.

An expression is either:

- `Person → BELIEVES → Belief`; or
- `Person|Company → PUBLISHED → Content → EXPRESSES → Belief`.

A direct `BELIEVES` observation backed by the same evidence as a content expression is
deduplicated. Syndication clustering beyond the existing evidence deduplication is not
yet implemented and remains a coverage limitation.

## Actor Lead Score

Calculated for an Actor–Belief pair:

```text
0.25 × sat(actor expressions, 5)
+ 0.25 × percent of other independent groups first observed later
+ 0.25 × sat(independent groups adopting later, 5)
+ 0.15 × sat(companies with later ACTS_ON edges, 3)
+ 0.10 × sat(qualifying commercial events after those actions, 2)
```

Qualifying commercial events are explicit company `PARTICIPATED_IN` links to dated
events with subtype acquisition, deployment, investment, observed outcome, partnership,
or pricing change. A later timestamp means sequence only, not causation.

## Actor Influence Score

Calculated for an Actor–Belief pair:

```text
0.20 × temporal lead
+ 0.30 × sat(explicit INFLUENCES or AMPLIFIES edges, 3)
+ 0.25 × sat(independent groups adopting later, 5)
+ 0.15 × sat(companies acting later, 3)
+ 0.10 × sat(repeated actor expressions, 3)
```

Raw view, like, repost, follower, or mention counts do not appear in the formula.
Popularity is never substituted for an explicit propagation path. Without an explicit
`INFLUENCES` or `AMPLIFIES` edge, that 30-point component is zero and the reason is shown.

## Belief Velocity

Calculated for a Belief across a current and previous window:

```text
momentum(current, previous) =
  0                                      when both counts are zero
  clamp(50 + 50×(current-previous)/(current+previous), 0, 100) otherwise

0.40 × independent-adopter momentum
+ 0.25 × expression momentum
+ 0.20 × acting-company momentum
+ 0.15 × recency of the latest expression within one window
```

The result includes `accelerating`, `stable`, or `decelerating` as a descriptive label.
It does not infer the mechanism behind the change.

## Belief Diversity

```text
0.35 × normalized Shannon entropy of source families
+ 0.35 × normalized Shannon entropy of independent actor groups
+ 0.20 × sat(distinct observed organizations, 5)
+ 0.10 × sat(distinct explicit stances, 3)
```

A belief repeated many times by one community remains low-diversity. Source family is
the stored source type plus URL host. Diversity measures breadth in the collected corpus,
not breadth across the whole world.

## Action Conversion

A company is exposed only when it has an explicit
`Company → PUBLISHED → Content → EXPRESSES → Belief` path. A converter must have a later
explicit `Company → ACTS_ON → Belief` edge.

```text
0.40 × converters / explicitly exposed companies
+ 0.20 × sat(converter companies, 3)
+ 0.20 × sat(qualifying later commercial events, 5)
+ 0.10 × mean(max(0, 1-lag_days/180)) × 100
+ 0.10 × sat(independent action-evidence source families, 5)
```

Employee speech is not silently treated as company exposure. With no company exposure,
conversion is undefined, represented as zero, and called out as a coverage gap.

## Evidence Confidence

Evidence Confidence is an auditability and corroboration score, not semantic truth and
not an LLM probability:

```text
0.25 × provenance-field completeness
+ 0.25 × sat(independent supporting groups, 3)
+ 0.20 × retrievable exact-span coverage
+ 0.15 × publication/valid-time coverage
+ 0.15 × extraction auditability rubric
```

The fixed auditability rubric is source-explicit/deterministic 100, analyst 80, derived
60, model-extracted with model + prompt + exact span 70, and model-extracted with
incomplete lineage 40. This is a disclosed governance rule. Stored model confidence and
assertion confidence values are never score inputs.

## Inspecting “why 82?”

`memesis explain-score --score-id UUID` returns every component's 0–100 value, weight,
point contribution, count basis, evidence IDs, reconciliation sum, and caveat. The stored
formula and version make historical results reproducible after the implementation changes.

## Known v0 limits

- Scores are not calibrated against future market outcomes.
- No causal claim follows from temporal sequence.
- Missing sources lower measured coverage but cannot describe unobserved activity.
- Independence uses known organizational affiliation and source family, not bot or
  coordinated-amplification detection.
- Saturation targets and weights are explicit product hypotheses, not learned parameters.
- Comparisons across markets with radically different source coverage are unsafe until a
  retrospective calibration dataset exists.
