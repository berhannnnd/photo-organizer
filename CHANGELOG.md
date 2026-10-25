# Changelog

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
