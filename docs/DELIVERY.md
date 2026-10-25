# Delivery and release evidence

Date: 2026-10-25. Development resumed by explicit user instruction after PRD v0.6.
The goal is a community-usable project, not a fixed demo. This checklist does not narrow
any PRD requirement. An unchecked item is not delivered merely because its design exists.

## Current foundation

- [x] Shared JSON service boundary and CLI; optional official-SDK stdio MCP transport.
- [x] Portable Skill with actual capability discovery and explicit fallback limits.
- [x] Persistent result membership, parent filtering, pagination, restart reuse and stale rejection.
- [x] Conservative boolean conditions, explicit unknowns, no negative inference from absent tags.
- [x] Non-destructive plan/export, no-clobber execution, receipts and source revalidation.
- [x] Optional explicit model config, with no mandatory CC Switch/Nexus dependency.
- [x] Packaging metadata, bundled Skill, local install instructions, test CI definition.

## Required before community release

- [ ] Versioned catalog migrations and consistent root/scan revision contracts.
- [ ] Complete incremental lifecycle: offline roots, move identity, partial scans, watcher,
      stage invalidation and retention. Current scan handles basic addition/change/deletion only.
- [ ] Durable tasks with pause/cancel/recovery, budgets, bounded scheduling and query priority.
- [ ] Image/text embedding provider, model digest isolation, query caching and mixed retrieval.
- [ ] Separate unknown vs unanalyzed evidence throughout the query and result model.
- [ ] Full multi-level/group-overlap/naming rules and persistent user corrections.
- [ ] Automatic grouping, same-person capability, OCR precision paths and fine-detail review.
- [ ] Provider capability probes and complete structured diagnostic/error taxonomy.
- [ ] Full-scope semantic coverage ledger and remaining set algebra operations.
- [ ] Independent host acceptance through both CLI and MCP; a test SDK client is not a second agent host.
- [ ] Fixed held-out semantic benchmark, human quality assessment and load performance gates.
- [ ] Clean-environment installation and remote CI results on every supported platform.
- [ ] Select open-source code license, review image/source licensing and publish repository/package.

## Local evidence

The original 15 prototype tests passed before modification. New regression tests cover
cross-process result reuse, new-file scope exclusion, stale source rejection, conservative
boolean logic, overlapping rules, explicit provider configuration and album revalidation.
The automated MCP integration test uses the official client to start a real stdio server,
then runs scan → search → refinement → plan → apply and checks CLI reads the same result.
Run results are recorded in `benchmarks/results/` locally; they are not semantic accuracy claims.

Local macOS tests do not establish Linux CI or Windows compatibility. No remote model
request or full-library model indexing is needed for these foundational checks.

### Verified in this development batch

- 23 tests passed in the development environment, including a real MCP stdio roundtrip.
- A wheel installed in a new isolated virtual environment (not editable, no repository
  import path); all 23 tests passed again, with the bundled Skill present.
- Wheel and source archive built successfully. Distribution contents exclude photographs,
  local catalogs and credentials; source archive includes the documentation.
- Skill frontmatter/reference validation passed.
- Existing catalog still contains 1000 files; 109 have historical completed visual facts,
  1 historical error, 890 pending, and 0 capture dates. This batch made no model requests.
- Metadata-only snapshot creation on a temporary backup of that 1000-file catalog:
  50 measurements, median 4.91 ms, p95 5.47 ms. This is a narrow local measurement,
  not semantic-search latency or completion of the PRD performance protocol.

Implementation order from here: finish catalog/task lifecycle and incremental consistency;
then integrate the installed Ollama artifact and mixed retrieval; then complete composable
organization rules and user corrections; finally run independent-host and fixed quality
acceptance. Packaging, regression tests and capability documentation evolve with each batch.
