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
- Search into a persistent result ID. Use `parent_id` for second-stage filtering or
  retrieval; use explicit selections or set operations to compose results. Pagination
  does not change membership. A broader request needs a broader parent scope.
- Keep vector candidates distinct from semantic matches. Review exact outstanding
  criteria and filter by those judgments to establish matches, or record an explicit
  agent/user selection when asked to curate freely. `order` only ranks members.
  Selecting candidates for organization is permitted within user authorization,
  but does not prove their semantics. Report ranked-subset coverage even after review;
  Top-K cannot prove an exhaustive library search.
- Inspect unknown, unanalyzed, failed and stale counts separately. Missing tags are
  not evidence of absence. Boolean negatives require actual evidence. Use bounded
  image/crop reads for visual inspection or configured vision review for text-only
  hosts; submit observations with file IDs, hashes, source and condition version.
- Compose groups freely using nested paths and membership IDs. Rename, merge or
  split through successor proposals. Choose overlap precedence or multi-membership
  according to user intent. Plan with the whole selected result ID, inspect actions,
  counts, target and conflicts, then apply within existing authorization. Do not ask
  again for the same authorized action. Originals remain unchanged.
- For larger work use durable jobs with scope and budgets. Report `needs_input`,
  partial failures and in-flight control boundaries. Resume preserved progress;
  inspect execution receipts before retrying. A collection can be selected again.

Reuse prior scope and preference decisions. Ask only when missing information changes
what photos or output the user wants. Subjective choices may be made when delegated;
state the criterion instead of presenting it as universal. Never claim real-model
accuracy, exhaustive coverage or independent-host acceptance from local code tests.
