# Tool contract v1 (alpha)

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
`verdict` can be `matched`, `not_matched`, `unknown_or_unanalyzed`, or `error`.
Unknowns can be inspected separately, but are never silently included in matched members.
Parent refinement acts on matched members only. A stale parent must be explicitly refreshed.

Plan modes: `album`, `copy`, `compress`. Copy/compress require an absolute `target`
outside all source roots. `spec` accepts `result_set_id` (or legacy `filter`, not both),
`group_by: none|month|category|rules`, `groups: [{name,where}]`, `quality: 1..95`,
`long_edge: 64..8192`. Overlap is currently rejected for clarification.
Group and quality options beyond this contract are unsupported, not silently ignored.

Vision indexing uses:
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
matches. Refining them inherits candidate status and cannot expand their scope.

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

`call describe-index` embeds current visual descriptions in the same model space. Default
retrieval uses reciprocal-rank fusion only when both channels cover the selected scope;
otherwise it explicitly reports image-only ranking and description coverage.
