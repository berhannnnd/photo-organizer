# Changelog

## 0.2.0a2 — unreleased

- Split source into domain packages and separate unit/integration tests; enforce Ruff style in CI.
- Add explicit selections, set composition, host evidence/vectors and persistent collections.
- Add configurable visual capability adapters, grouping suggestions and durable job checkpoints.
- Preserve unresolved semantic requirements through repeated retrieval and composed result sets.
- Share operation discovery between CLI and MCP and update the portable Skill workflow.

- Add digest-bound local Ollama image/text index, cached queries and optional image/description rank fusion.
- Keep retrieved candidates distinct from verified matches and preserve candidate provenance through refinement.
- Support up to eight grouping levels and explicit unique/priority/multiple membership policies.
- Allow scoped GLM condition review without revisiting unrelated images.
- Release the global library lock during visual indexing; bound in-flight requests.
- Add a real GLM tool-calling Skill test harness and fixed scenario definitions.

## 0.2.0a1 — unreleased

- Add shared JSON service operations and optional MCP stdio tools.
- Persist search results with parent-scoped filtering and stable pagination.
- Reject stale snapshots and overlapping categories instead of silently changing scope.
- Use conservative AND/OR/NOT: missing tags are unknown, not evidence of absence.
- Accept explicit Anthropic-compatible provider config with environment secret references;
  CC Switch is no longer required for visual indexing.
- Verify original content before applying logical albums; reject non-regular sources.
- Package the portable Skill and add install/contribution guidance and CI configuration.

Still an alpha: see the delivery checklist for incomplete PRD contracts and release gates.
