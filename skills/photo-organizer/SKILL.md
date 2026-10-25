---
name: photo-organizer
description: Search and organize local photographs using the photo-organizer engine, persistent result sets, and non-destructive export plans. Use for photo-library search, repeated filtering, grouping, and compression. Requires a locally installed engine or its MCP server.
---

Use the engine for file operations; do not generate ad hoc traversal or move scripts.
Read [tools](references/tools.md) for commands, rule syntax, and current limitations.

1. Discover actual capabilities using `photo_capabilities` or the CLI equivalent. The target PRD is not evidence that a feature is implemented. Reuse the user's chosen library state directory across turns.
2. Clarify missing decisions that materially change scope, subjective criteria, grouping, or output. Reuse answers already given. If the user delegates exploration, explain the chosen criteria and return candidates; do not invent a universal meaning of subjective words. Waiting is not consent.
3. Sync authorized source roots when freshness matters. Use existing index coverage to decide whether a task can proceed. Metadata operations need no model. Never infer capture dates from download times or names from faces.
4. For visual indexing, explain required capability and transmission scope. Accept an explicit config/environment reference or an available authorized host tool; never retrieve a host's login token. Missing APIs must yield a disclosed limited mode, not fabricated visual facts. No model is downloaded automatically.
5. Search into a persistent result ID. A second filter uses `parent_id`; a broader request may require the parent or library scope. Pagination is not a smaller selection. If “those” could refer to multiple results, ask which.
6. Absence from tags is unknown, not proof of absence. Boolean negatives require explicit evidence. Report unknown, unanalyzed, failed, stale, and unavailable information; the current engine combines unknown/unanalyzed counts. Indexed model judgments are fallible.
7. Plan using `result_set_id` to organize the entire selected snapshot. Inspect counts, grouping, conflicts, target and source state. Resolve material ambiguities; execute within existing user authorization without asking again for the same action.
8. Use `photo_apply` or CLI equivalent for approved plans. Originals remain unchanged. Reconcile receipts before retrying; never overwrite a destination, treat a filtered-history rollback as file rollback, or claim success with failed items.

Current alpha supports deterministic metadata and indexed evidence. Open semantic embedding search, automatic grouping, same-person clustering, arbitrary multi-level grouping and durable background jobs are not yet available. If the request needs them, explain the gap; do not disguise keyword matching as equivalent search. Do not claim community release readiness from a local smoke test.
