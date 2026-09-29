# Memesis Licenses and Data-Rights Register

Status: architecture-stage compliance register  
Audit date: 2026-09-29  

This is an engineering compliance plan, not legal advice. It distinguishes software licenses from the rights and platform terms attached to collected content; a permissive collector does not make collected content permissively licensed.

## Selected software

| Component | Planned use | License | Required action before distribution |
|---|---|---|---|
| PostgreSQL | Primary database | PostgreSQL License | Include its license if redistributed; hosted use normally adds no distribution duty |
| Trafilatura | HTML text/metadata extraction | Apache-2.0 | Preserve license and notices, identify modifications, and retain NOTICE material if applicable |
| FastAPI | HTTP API | MIT | Preserve copyright and permission notice in distributed copies |
| Pydantic | Typed validation | MIT | Preserve copyright and permission notice in distributed copies |
| HTTP/feed client libraries | Collection | Confirm exact package/version during lockfile review | Generate notices from the final resolved dependency tree |
| React | Frontend | MIT | Preserve copyright and permission notice in distributed copies |
| Cytoscape.js | Graph visualization | MIT | Preserve copyright and permission notice in distributed copies |
| pgvector | Deferred vector search | PostgreSQL License | Include license if later bundled or redistributed |

The implementation must generate a software bill of materials and third-party notices from the actual lockfiles. This document does not substitute for that version-specific review.

## Audited but not selected as runtime dependencies

| Component | License | Consequence of the decision |
|---|---|---|
| Graphiti | Apache-2.0 | Pattern-only use; do not copy code without recording attribution, notice, changed-file, and patent obligations |
| Harken | MIT | Pattern-only use; retain its MIT notice if adapter code is copied later |
| Crawl4AI | Apache-2.0 | No first-slice dependency; a later integration requires normal Apache compliance and review of README attribution language |
| `openalex-elastic-api` | MIT | No code or runtime use planned |
| `openalex-guts` | MIT | No code or runtime use planned |
| `openalex-walden` | MIT | No code or runtime use planned |
| `openalex-official` | MIT | No first-slice use; include its notice if later shipped with a bulk pipeline |
| Jetstream server | Dual MIT/Apache-2.0 | API use only; if code is later embedded or redistributed, choose Apache-2.0 and document that choice |
| LightRAG | MIT | No code or runtime use planned |
| Scrapling | BSD-3-Clause | Deferred; retain copyright, conditions, disclaimer, and non-endorsement rule if adopted |

## Source-data rights

### OpenAlex

[OpenAlex metadata is CC0](https://help.openalex.org/data/how-its-built/), so its bibliographic records can be reused without an attribution requirement. Memesis should still record OpenAlex as provenance and its retrieval date for reproducibility.

OpenAlex-linked abstracts and full text are a separate issue. A paper, XML file, or PDF retains its own publisher/author license; [OpenAlex explicitly says its PDFs keep their original copyright](https://help.openalex.org/access/fulltext/). Store license metadata per work; default to metadata, identifiers, short evidence snippets, and source links. Do not bulk-store or redistribute full text without a rights rule that permits it.

### Bluesky

Jetstream's software license does not license user posts. Public availability is not a copyright grant. The source-policy register must record applicable Bluesky terms and retention rules. Store only fields needed for evidence, keep the AT URI/DID/cursor, process delete and account-status events, and prevent a deleted post from appearing in new answers. Historical audit retention, if any, must be access-controlled and justified separately.

### Company sites, blogs, documentation, and RSS

Copyright remains with the publisher unless a page declares another license. Robots directives and terms of service are access controls, not copyright licenses, and both must be reviewed. For ordinary copyrighted pages, retain URL, metadata, content hash, extracted facts, and the minimum exact spans needed for substantiation. Do not republish full articles or create a public mirror.

### Hacker News and GitHub

Use official APIs and comply with their current terms and rate limits. User comments, repository README files, issues, and release prose retain their authors' licenses or copyrights. Repository source licenses apply to source code; they do not automatically cover all user-generated discussion. Store the minimum necessary evidence and link back to the canonical object.

### Model providers

Provider terms must allow submitted content, requested retention settings, and commercial output use. The model gateway must record provider, model, region if relevant, retention setting, and whether training on submitted data is disabled. Do not send secrets, private licensed corpora, or unnecessary personal data.

## The principal licensing risk

The largest risk is not an open-source license. It is collecting, retaining, and redistributing third-party posts and web content as though public access were a reuse license. This risk grows if Memesis exposes long quotations, reconstructs deleted posts, uses unofficial authenticated scraping, or redistributes paper full text.

The control is a versioned `source_policy` registry enforced before collection:

| Required field | Purpose |
|---|---|
| source and access method | Distinguish official API, public HTTP, feed, manual import, and authenticated access |
| terms/robots URLs and reviewed date | Make access decisions auditable and expirable |
| permitted fields and purpose | Enforce data minimization |
| raw-content and evidence-span retention | Avoid indefinite default retention |
| redistribution rule | Separate internal analysis from public display |
| deletion/tombstone behavior | Propagate removals to retrieval and presentation |
| personal-data classification | Trigger privacy and access controls |
| jurisdiction/owner/approval | Route uncertain policies for legal review |

An adapter must fail closed when it has no active source policy.

## Explicitly prohibited without a new review

- unofficial X or LinkedIn session-cookie scraping;
- CAPTCHA bypass, credential sharing, or rotating proxies intended to evade access controls;
- bulk PDF/full-text acquisition merely because a URL is available;
- exposing raw collected content through a public API;
- training a model on the corpus without separate rights analysis;
- copying source code from a pattern-only repository without provenance and license records;
- presenting an inferred private belief as a fact about a person.

## Release gate

Before any deployed or distributed build:

1. produce an SBOM from resolved Python and JavaScript lockfiles;
2. generate `THIRD_PARTY_NOTICES` and verify Apache `NOTICE` propagation;
3. review all non-permissive, source-available, unknown, or license-missing transitive packages;
4. verify every active connector has a current source policy;
5. test deletion/tombstone propagation from ingestion through retrieval and UI;
6. sample generated answers for excessive quotation or content reconstruction;
7. obtain counsel review before public redistribution or collection from a materially new source family.
