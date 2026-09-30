# Market and date scope

Workspace reads and answers now share `ScopedGraphRepository`. The selected market
is an anchor for evidence-backed graph traversal. People, beliefs and company actions
can be discovered through connections even when their names do not match the question.
Empty markets return empty data and coverage gaps, rather than global fallback lists.

The defaults are an inclusive publication cutoff of now, no lower date bound, three
graph hops, and explicit adjacent-market exploration enabled. Source timestamps fall
back to retrieval time when publication time is missing. Naive timestamps are UTC.

## API

Get the market ID from `GET /api/markets`. All market GET routes accept these query
parameters; the ask route accepts the same fields in its JSON body:

```json
{
  "question": "Which connected signals challenge our market assumptions?",
  "start_at": "2026-09-01T00:00:00Z",
  "as_of": "2026-09-30T23:59:59Z",
  "time_basis": "published_at",
  "graph_hops": 3,
  "include_adjacent_markets": true
}
```

Submit to `POST /api/markets/{market_id}/ask`. The market ID in the URL is binding.
`GET /api/markets/{market_id}` accepts the fields as query parameters. Existing clients
that send only a question continue to work with the defaults. No frontend edits are
needed for market isolation; date controls can be added to the frontend later.

`graph_hops` accepts 1–6. Adjacent branches need a sourced `ADJACENT_TO` edge directly
from the selected market. Explicitly tagged foreign-market sources are excluded unless
they also name the selected or admitted adjacent market. An actor's presence never
imports all their unlinked posts. Untagged material needs a graph path or market-anchor
provenance, so market membership is only as good as the stored links.

`published_at` supports retrospective source-date research, including older material
collected later. `known_at` additionally requires collection and edge recording by the
cutoff and excludes source versions updated after it. Both modes exclude future
publication and future effective relationship dates.
Canonical names and attributes are not versioned, so neither mode claims to reproduce
the entire historical database state.

The response includes `query_scope` and `coverage`: resolved dates, exploration settings,
included adjacent markets, counts before and after retrieval limits, missing publication
dates and the actual evidence date range. Each source has `scope_membership`. Workspace
graph nodes include distance from the market anchor. Timeline output remains capped at
100 records, with both total and returned counts available.

Scores are recomputed from the scoped graph; globally cached scores are not reused.
With an explicit lower bound, velocity uses two daily comparison windows that fit inside
the requested interval. If the interval cannot contain both, velocity is unavailable and
market motion cannot claim acceleration from an excluded baseline. Score windows appear
in answer packets, and workspace beliefs include `velocity_available`.

Scope and coverage are included in packet fingerprints and saved reasoning answers.
Full-context retrieval removes ranking budgets while respecting the same scope.

## CLI

```powershell
uv run memesis ask "Which connected signals matter?" --market-id <UUID> --start-at 2026-09-01T00:00:00Z --as-of 2026-09-30T23:59:59Z --graph-hops 4
```

Use `--time-basis known_at` for the additional knowledge cutoff, and
`--no-adjacent-markets` to exclude adjacent branches. `--full-context` retains the
market/date boundary. Without `--market-id`, CLI queries remain cross-market but respect
the requested date boundary. An inferred last-30-days window is used only when an
explicit lower bound was not provided.

This changes evidence selection and scoring boundaries. Existing deterministic answer
templates still have topic-specific assumptions; scope enforcement alone does not turn
them into a general reasoning model.
