# Tool contract v2 (alpha)

MCP names: `photo_capabilities`, `photo_status`, `photo_scan`, `photo_search`,
`photo_results`, `photo_plan`, `photo_apply`.

The same engine is exposed by CLI:

```sh
photo-organizer --state /absolute/library-state call capabilities
photo-organizer --state /absolute/library-state call scan --args '{"root":"/absolute/photos"}'
photo-organizer --state /absolute/library-state call search --args '{"rule":{"date_from":"2024-01-01","date_to":"2024-12-31"}}'
photo-organizer --state /absolute/library-state call search --args '{"rule":{"orientation":"landscape"},"parent_id":"RESULT_ID"}'
photo-organizer --state /absolute/library-state call results --args '{"result_id":"RESULT_ID","limit":50,"offset":0}'
photo-organizer --state /absolute/library-state call plan --args '{"spec":{"result_set_id":"RESULT_ID","group_by":"month"},"mode":"album"}'
photo-organizer --state /absolute/library-state call apply --args '{"plan_id":"PLAN_ID"}'
```

All `call` responses have `api_version`, `status`, `data`, `error`.
A nonzero CLI exit denotes failed/partial execution. Read individual errors.
Legacy direct commands are retained for compatibility; use `call` for new integrations.

Rules support `and: [rules]`, `or: [rules]`, `not: rule`, `date_from`, `date_to`,
`orientation: landscape|portrait|square`, `all_tags`, `any_tags`, `not_tags`,
`caption_text`, `category`, and `semantic` (an exact previously evaluated criterion).
`semantic` does not call a model or perform vector search. Unknown evidence remains unknown.
No user-provided SQL or executable expressions are accepted.

Result pages have a stable ID, parent ID, membership counts, stale count, and next offset.
`verdict` can be `matched`, `candidate`, `not_matched`, `unknown`, `unanalyzed`, or `error` (legacy results may contain `unknown_or_unanalyzed`).
Unknowns can be inspected separately, but are never silently included in matched members.
Parent refinement acts on matched and candidate members only. A stale parent must be explicitly refreshed.

Plan modes: `album`, `copy`, `compress`. Copy/compress require an absolute `target`
outside all source roots. `spec` accepts `result_set_id` (or legacy `filter`, not both),
`group_by: none|month|category|rules`, `groups: [{name,where}]`, `quality: 1..95`,
`long_edge: 64..8192`. Rule-based levels accept an explicit overlap policy as described below.
Group and quality options beyond this contract are unsupported, not silently ignored.

Legacy explicit-config vision indexing uses:
`photo-organizer --state /absolute/library-state index --config /absolute/provider.json --limit 5`.
Config fields: `protocol: anthropic`, exact HTTPS `endpoint`, `model`, `api_key_env`.
Only read the named environment variable. Larger batches follow actual user scope and budget.
Missing vision still permits metadata search and non-destructive export.
The optional legacy CC Switch import is not required for installation or ordinary use.


## Image/text retrieval and composable grouping

`photo_retrieve(text, top_k=30, parent_id=null, model="embeddinggemma-2:latest")`
returns a persistent ranked candidate set. CLI operation: `retrieve`. Build the local
index first with `call embed-index`; it never downloads a model and binds vectors
to the exact installed artifact digest. Local query encoding is still a model call;
repeated identical queries reuse the versioned vector cache.

Candidate sets require `accept_candidates: true` in plan specs when the user has
explicitly requested organization of candidates. Do not portray these as verified
matches. Refinement cannot expand their scope. Only proving outstanding semantic criteria or making an explicit selection removes the candidate restriction.

`levels` replaces legacy `group_by` and `groups`, supports up to eight levels:
`[{"field":"year"},{"field":"category"},{"field":"orientation"}]`.
Fields: `year`, `month`, `category`, `orientation`, `none`.
A rules level: `{"rules":[{"name":"Cats","where":{"all_tags":["cat"]}}],"overlap":"error"}`.
Overlap: `error` (ask), `first` (explicit precedence), `multi` (all matching groups).
Unknown rule judgments enter `needs-review`, and proven nonmatches enter `unclassified`.
Counts distinguish selected photos from expanded memberships.

`photo_enrich(result_set_id, condition)` can evaluate a new
criterion using the host's configured vision provider. Start the MCP server with
`--vision-config /absolute/provider.json`; without this option it reports missing capability. CLI equivalent: `enrich --config CONFIG --condition
CRITERION --result-set-id ID`. Subsequent search uses `semantic: CRITERION` inside the
same parent scope. This is needed when negative/relational facts cannot be proven by tags.

`call describe-index` embeds current visual descriptions using the configured description-text role, or the image/text model when no separate role is configured. Retrieval fuses channel ranks, never vectors from different spaces, and reports each channel's coverage. `allow_text_fallback: true` explicitly permits literal OCR/caption fallback when an encoder is unavailable; inspect returned failures.

## Composable selections and evidence

Use `photo_call(operation, arguments)` for extended operations. Discover their
arguments through `photo_operation_schema`; CLI uses `call operation-schema --args '{"operation":"select"}'`. Both return the standard response envelope. CLI uses the same `call` operations.

- `select(result_id, ids, mode=keep|exclude|order, source=agent|user, reason)`
  saves an explicit selection. `order` includes every current member. Explicit
  selection permits organization but is not a semantic proof.
- `combine(result_ids, operation=union|intersection|difference, identity=file|content)`
  creates a new snapshot, preserving input provenance and duplicate mappings.
- `image(result_id, file_id, long_edge=1280, crop=null)` returns a bounded JPEG as
  base64 plus its content identity; crop uses oriented image pixel coordinates.
- `evidence-read(result_id, condition, limit=50, offset=0)` returns the active
  condition version and observations. `evidence-submit(result_id, records, source,
  condition, expected_version)` accepts up to 100 scoped judgments or visual labels.
  Records require file_id/hash and verdict/evidence (or observation for labels).
  Source is `{kind: host|provider|user, model?, version?}`. Pass the read version
  when the condition already exists. Never mark an agent inference as a user correction.
- `group-propose(result_id, groups, parent_id?, overlap=error|first|multi, reason)`
  saves immutable groups `{path: [names], ids: [file IDs]}`; submitting a successor
  implements rename, merge, split and membership corrections without rewriting history.
- Plan with `group_spec_id` and the same `result_set_id`, or use rule-based levels.
  `name_template` supports year/month/day/category/original/sequence/id/hash.
  `max_bytes` on compression fails explicitly if the size target cannot be met.
- `plan-read(plan_id, limit, offset)` reads actions and receipts. `collection()`
  lists persistent collections; `collection(collection_id, name?, group?)` returns
  a reusable result ID, optionally for one nested group.

Unknown and unanalyzed are now separate verdicts. A candidate's exact retrieval
criterion can be reviewed and used as a semantic filter to produce evidence matches;
its context still reports ranked-subset coverage. Filtering only by unrelated metadata
does not prove the original semantic request.


## Configurable capabilities and persistent work

Discover accepted arguments before calling an unfamiliar operation. Role names are
`vision`, `image_text`, `description_text`, `ocr`, `faces`. Use `capability-configure`,
`capability-probe` and `capability-status`. Credentials are named environment references;
never embed secrets in result records or provider URLs. Host capabilities use explicit
submission rather than pretending the engine can invoke an arbitrary host tool.

- `vector-submit` imports bounded host image/query vectors with a declared space,
  model and revision. `vector-search` uses a cached query or reference photo in that
  exact space. `retrieve` calls a configured encoder and fuses available channels.
- `analysis-submit` accepts scoped OCR/quality observations; `analyze` invokes the
  configured OCR service or local technical metrics. `text-search` returns literal
  candidates, not semantic proof. `rank` preserves scope and reports unmeasured items.
- `face-submit`, `people-cluster` and `people` support face features and editable
  identities. `group-suggest` proposes themes, events, people, duplicates or similar
  images; inspect its evidence before adopting the proposal.
- `job-start`, `job-status`, `job-control` and `job-recover` persist work across
  requests. Poll status; queued/running is not completion. Pause/cancel stop future
  dispatch after an in-flight item finishes. Missing capabilities produce needs-input.
- `roots`, `sync`, `watch` and `cache-cleanup` manage registered libraries, optional
  polling and derivative retention. Offline roots do not mean their photos were deleted.

Technical quality scores are descriptive signals, not calibrated aesthetic judgments.
Face and semantic quality depend on the actual configured models and photo collection.

## Rules, corrections and completeness

`operation-schema` returns `input_schema` (JSON Schema 2020-12) in addition to argument
names/defaults. The service validates it before dispatch. Query rules also support
explicit `date_basis: capture|import|modified`, `roots`, `path_prefix`, `person_ids`,
`location_box: [south,west,north,east]`, decoded `formats`, width/height and byte bounds.
Plan `spec.date_basis` controls date grouping/naming; do not silently substitute file dates.

- `metadata-correct(result_id, records, reason)` takes `{file_id,hash,changes}` records.
  Fields: taken, category, caption, latitude, longitude, tags, notes. This records
  user-authorized corrections; machine observations remain intact. Null resets a field
  to machine evidence. `metadata-history` pages the audit history.
- `coverage(result_id, condition?)` accounts for the entire frozen result scope,
  including unknown/unanalyzed members. Review this before claiming exhaustive work.
  `results` exposes root revisions, unavailable members and evidence-change indicators.
- `review-detail` performs configured high-resolution/crop review. For visual hosts,
  `photo_image` returns native MCP image content. Scoped unknown members can be inspected.
- `group-read(group_spec_id, group?, limit, offset)` pages summaries or IDs in a named
  group. `people`, `collection` and job listings also have bounded pages.
- `recipe-save(name, rule?, result_id?, preference?, recipe_id?, expected_version?)`
  remembers a rule/preference only when the user asks. Supply exactly one dynamic rule
  or frozen result ID. `recipe-read` reads it; `recipe-materialize` explicitly reevaluates
  a dynamic rule or returns the frozen snapshot. Editing requires its current version.

An explicit selection stays an explicit selection after refinement; it does not become
objective semantic truth. Capture a new result after corrections when new membership
is desired. Existing snapshots never silently expand. Plans reject known offline roots,
existing target paths and unsafe ancestors; execution checks again for intervening changes.
