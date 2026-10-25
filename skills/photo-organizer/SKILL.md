---
name: photo-organizer
description: Search, refine, group and organize local photos through persistent selections and non-destructive export plans. Use with the photo-organizer CLI or MCP engine; supports text-only agents with configured visual services.
---

The host agent chooses the workflow and grouping. The engine owns indexing, scoped
evidence, persistent selections and file execution. Read [tools](references/tools.md)
for operation discovery and examples; use the same library state across turns.

- Discover capabilities and configured roles before choosing an analysis route.
  Metadata needs no model. For visual tasks, use an authorized host tool or configure
  OCR, image/text embedding, vision or face endpoints separately. A text-only agent
  can use those services. Missing capabilities require configuration or a disclosed
  limited workflow; never invent observations or read another application's login tokens.
  Explain remote image transmission when configuring a remote provider. No models
  are downloaded automatically; a successful probe verifies protocol, not quality.
- Sync authorized roots when freshness matters. Capture dates, file timestamps and
  import times are different evidence. Faces receive stable cluster IDs, not guessed
  real names. Read the user's corrections before making another inference.
  Before costly retrieval/review or organization, identify the request's hard
  constraints. If required identity, time, place or preference evidence is unavailable,
  ask for the missing definition/reference or permission to relax that constraint.
  Visual resemblance cannot establish a named person's identity, exact place or date.
  If the user cannot supply it, explain the missing evidence and stop that dependent
  workflow; do not spend model calls trying to prove nonvisual facts from appearance.
  Supplying one clue narrows the task but does not satisfy its other hard constraints.
  State which requirements still need evidence and which model roles need configuration.
- Search into a persistent result ID. Use `parent_id` for second-stage filtering or
  retrieval; use explicit selections or set operations to compose results. Pagination
  does not change membership. A broader request needs a broader parent scope.
  The returned `result_set_id` identifies the selected result; returned `parent_id`
  identifies its broader ancestor. Pass the selected result's ID to scoped review,
  filtering and organization, and check its member count before a model batch.
  A `select`, `combine` or refinement creates a new result ID: use that new ID for
  subsequent grouping and planning. A grouping proposal belongs to exactly that
  selection. Its optional `parent_id` refers to an earlier grouping proposal for
  edits, not to a search result or its ancestor.
- Keep vector candidates distinct from semantic matches. Review exact outstanding
  criteria and filter by those judgments to establish matches, or record an explicit
  agent/user selection when asked to curate freely. `order` only ranks members.
  Selecting candidates for organization is permitted within user authorization,
  but does not prove their semantics. Report ranked-subset coverage even after review;
  Top-K cannot prove an exhaustive library search.
  Match analysis cost to the requested assurance. For exploratory/candidate-only
  previews, retrieve and curate from indexed evidence first; do not automatically
  review every recalled photo. Use bounded visual review when the user needs a
  verified condition (especially absence/count/relationships), or when essential
  evidence is missing, and preserve results for reuse. Candidate curation does not
  need to be upgraded to a semantic proof merely to return a useful preview.
- Inspect unknown, unanalyzed, failed and stale counts separately. Missing tags are
  not evidence of absence. Boolean negatives require actual evidence. Use bounded
  image/crop reads for visual inspection or configured vision review for text-only
  hosts; submit observations with file IDs, hashes, source and condition version.
- Compose groups freely using nested paths and membership IDs. Rename, merge or
  split through successor proposals. Choose overlap precedence or multi-membership
  according to user intent. Plan with the whole selected result ID, inspect actions,
  counts, target and conflicts, then apply within existing authorization. Do not ask
  again for the same authorized action. Originals remain unchanged.
  Map output requirements to the actual mode: `copy` preserves original bytes;
  resizing, JPEG conversion, quality or byte limits require `compress`. Confirm
  the preview's mode and dimensions/quality before applying, not after exporting.
  Report engine-provided totals and `selected_summary`; do not mentally sum large
  group tables. Distinguish selected-file totals from expanded memberships.
- Save cross-task preferences only when the user explicitly asks to remember them,
  using versioned recipes. Dynamic recipes refresh explicitly; keep frozen selections
  stable. Use the coverage ledger for complete-scope claims.
- For larger work use durable jobs with scope and budgets. Report `needs_input`,
  partial failures and in-flight control boundaries. Resume preserved progress;
  inspect execution receipts before retrying. A collection can be selected again.

Reuse prior scope and preference decisions. Ask only when missing information changes
what photos or output the user wants. For subjective criteria without prior preference
context, ask one short question about the desired direction or permission to choose.
An instruction to find photos delegates the action, not automatically the user's taste.
If the user explicitly delegates taste or requests open-ended exploration without
questions, choose a criterion, state it and return diverse candidates instead of
presenting that criterion as universal. Never claim real-model
accuracy, exhaustive coverage or independent-host acceptance from local code tests.
