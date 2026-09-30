# Decision engine benchmark — previous conclusions withdrawn

The previous report presented Jev/frontier accuracy, latency, cost and engine
selection recommendations as empirical results. They are not supported by its
implementation: the frontier engine runs local Jev-style rules, while offline
Jev uses calibrated rules. Both previously added invented latency and usage.
Their apparent agreement is not independent model evidence.

Those comparative figures and recommendations are withdrawn. The source history
retains the old report; it must not be used as product performance evidence.

The legacy runner now reports **draft fixture label agreement** and each result's
execution provenance. It is offline by default, excludes billed-cost claims,
and cannot declare a provider winner or rewrite this document with canned
recommendations. Explicit --allow-live-jev permits configured Jev calls; frontier
still remains a simulator, so this does not create a live paired comparison.

See [Intelligence evaluation](INTELLIGENCE_EVALUATION.md) for separate layer
diagnostics, human semantic review, decision usefulness, and a paired-provider
receipt audit. A real provider comparison needs independent executed adapters,
matched inputs/contracts, cache exclusion, repeated measurements and a reviewed
held-out set. No such comparison has been established by the current fixtures.
