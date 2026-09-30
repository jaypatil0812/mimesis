# Real-data test corpus — 1 October 2026

The local preview database now contains additional real public evidence from
GitHub projects, Hacker News and Hugging Face. Counts below compare evidence
rows against the backup taken immediately before this load. They exclude
existing fixtures; overlapping searches reuse evidence rather than counting it
as a new independent observation.

| Source | Additional unique evidence records |
| --- | ---: |
| Public GitHub issue/PR titles and bodies | 238 |
| Hacker News stories/comments | 185 |
| Hugging Face RSS entries | 200 |
| Total at this snapshot | 623 |

The database backup is outside Git at
`C:\Users\jaypa\AppData\Local\Temp\mimesis-before-corpus-3gdkgjev.sqlite3`.
Database contents remain local and are not included in the source commit.

## Inspect the investigations

- [Developer discussions](http://127.0.0.1:8000/api/investigations/a0b38d06-0d0a-43f0-8b0c-1a12af7371a1): inference cost, GPU memory and quantization; 90-day initial search window.
- [Technical feeds](http://127.0.0.1:8000/api/investigations/94b6821d-8eb1-488b-8908-fe7677a06d5b): Hugging Face and attempted PyTorch collection. RSS uses the publisher's available feed history, not a full archive or a guaranteed 90-day sample.
- [Inference project issues](http://127.0.0.1:8000/api/investigations/e0061dde-b486-4c7e-a66a-d9236835b41c): vLLM latency, SGLang memory, llama.cpp quantization and LiteLLM cost; updated in the initial 30-day window. Issue creation can precede that window.
- [API controls](http://127.0.0.1:8000/docs): inspect receipts, source health, pending extraction, snapshots and review patterns.

Saved configs are in `data/watchlists/test-corpus-*.json`, disabled by default
for portable reuse. The local instances are enabled with six-hour scan
intervals; incomplete scans and pending extraction may resume sooner. Follow-up
searches are disabled during this initial corpus load. The separate worker must
remain running for collection to continue.

## Real example records

- [vLLM heterogeneous parallelism proposal](https://github.com/vllm-project/vllm/issues/46107).
- [vLLM preemption selection proposal](https://github.com/vllm-project/vllm/issues/54644).
- [vLLM structured-output compilation timeout report](https://github.com/vllm-project/vllm/issues/54003).
- [vLLM grammar compilation and Kubernetes throttling report](https://github.com/vllm-project/vllm/issues/49460).

These are authors' reports and proposals. They do not independently verify the
defects, prove that features shipped, or measure customer adoption.

## What to test

1. Follow an observation to its preserved document, source URL and exact span.
2. Compare workload qualifications rather than merging all cost/latency claims.
3. Inspect connecting edge IDs and alternative explanations for proposed patterns.
4. Reject an unjustified explanation and inspect the append-only review history.
5. Re-run unchanged content and inspect cache reuse; change an interpretation
   version and inspect controlled reprocessing and projection-review warnings.
6. Inspect failed sources and incomplete pagination alongside last-update times.

This corpus is source-rooted research. It is not automatically assigned to the
AI infrastructure market, so existing market dashboards may not display all of
it. Market assignment requires supported relationships. Use the investigation
endpoints to inspect this load without weakening market boundaries.

PyTorch's feed and Bluesky continuation returned HTTP 403 during the load.
Those failures are visible coverage gaps. GitHub collection excludes comment
threads/releases. Hugging Face feed entries vary in length and are not all full
articles. Strategic reasoning remains unconfigured; structural candidates are
not a validated market analysis. Collection, extraction and semantic review are
separate stages, and the API reports any extraction backlog.
