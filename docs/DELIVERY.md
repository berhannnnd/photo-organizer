# Delivery and release evidence

Date: 2026-10-25. Target: PRD v0.7, portable Skill for tool-capable agents,
including text-only hosts with separately configured visual services. This document
separates implementation from acceptance; it does not reduce the PRD scope.

## Implemented development baseline

- Domain packages for storage, library, search, vision, capability adapters,
  organization, runtime and transports; thin compatibility entrypoints.
- Versioned catalog migration, registered root scans, rename identity, offline/partial
  scan handling, opt-in polling and derivative retention.
- Immutable results, explicit selection/ranking, set operations, scoped refinement,
  unknown/unanalyzed distinction, user semantic corrections and host evidence.
- Image/text and description vector spaces, host vector submission, reference-image
  retrieval, channel coverage and reciprocal-rank fusion with explicit text fallback.
- Role configuration and real-input probes for vision, embedding, OCR and faces;
  optional local engines and host submissions do not require host-native vision.
- Automatic grouping suggestions, editable nested groups, naming, overlap policies,
  collections, bounded compression, non-destructive export and action receipts.
- Durable job items, detached worker, pause/cancel/recovery, configuration revisions,
  retry limits and conservative request/image/time/cost bounds.
- CLI and MCP share operations and argument discovery; packaged Skill describes
  the actual workflow. Ruff formatting/lint and wheel/sdist builds are configured.

## Current validation

The current regression suite has 47 tests. It exercises real stdio MCP, a loopback
HTTP provider fixture, detached worker execution, snapshot composition, host vectors,
retrieval lineage, stale selection rejection, filesystem export and scan lifecycle.
Ruff lint and formatting checks pass. Wheel and source archive build successfully.
The wheel installed in a fresh virtual environment outside the checkout; all 47 tests
passed there too, and the bundled Skill was present. Skill validation also passed.
These are deterministic engineering checks, not evidence of real model accuracy.

Earlier local metadata latency measurements and catalog counts belong to an older
baseline and are not presented as current acceptance evidence. The benchmark tools
remain available for explicit model/collection testing.

## Open engineering audit

Before claiming the entire PRD implemented, close the following boundaries:

- Cross-job provider concurrency and interactive priority; cache-aware request budgets,
  durable binding of initially missing capabilities and Retry-After handling.
- Full typed operation schemas and bounded paging for every group/identity/collection
  response; configurable metadata corrections beyond semantic judgments.
- Result evidence freshness/coverage across every stage, offline snapshot planning,
  output collision reporting at plan time and color-profile normalization.
- Full regression coverage for separate description spaces, provider response failures,
  interrupted scans, nested root ownership and crash/control races.

## Acceptance still required

- Independent agent hosts through CLI and MCP; an SDK test client is not another host.
- Actual configured OCR/vision/embedding/face model checks, human-labeled held-out
  quality benchmark, complete-scope semantic coverage and library-scale load tests.
- Remote Linux/macOS CI results and supported-platform clean-environment installation.
- Final PRD traceability review before community release. Windows remains unsupported.

Do not treat a supported adapter, successful protocol probe or implemented operation
as a guarantee of semantic quality, exhaustive recall or completed release acceptance.
