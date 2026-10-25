# Changelog

## Unreleased — real-library integration

- Add native PaddleOCR HTTP configuration and validated text/coordinate extraction
  for the local Docker service.
- Accept grayscale/palette images carrying RGB ICC profiles; bump preprocessing
  identity so affected derivatives and model indexes cannot silently reuse old outputs.
- Expose composable operations to the GLM Skill test harness and preserve complete
  engine pages instead of truncating them behind an unchanged pagination cursor.
- Use corrected metadata consistently in field/rule grouping; reject resize options
  in byte-preserving copy plans before any export can execute.
- Make grouping schemas match runtime exclusivity/limits and clarify selection versus
  grouping-proposal identities. The test agent now consumes the engine's real schemas.
- Clarify missing hard evidence, scoped selection handoffs and export modes in the Skill.

## 0.2.0a3 — development candidate

- Complete endpoint-wide admission, foreground priority, actual request reservations,
  cached-stage reuse, Retry-After and configuration-bound atomic job commits.
- Add JSON Schema validation/discovery, native MCP images and high-resolution provider review.
- Add user metadata overlays, explicit date bases, format/size filters, paginated groups,
  reusable rules/preferences and per-stage scope coverage.
- Normalize embedded color profiles and transparency; preflight output conflicts and
  offline sources; checkpoint scans before atomic catalog updates.
- Add catalog migrations through v4, source/evidence revision reporting, independent-space
  retrieval tests and reproducible quality/kernel evaluation tools.
- Real-model quality, independent-agent acceptance and library-scale performance remain
  separate acceptance gates; this candidate does not claim those measurements.

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
