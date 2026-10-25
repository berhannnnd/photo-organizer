# Engineering structure

The Skill is the user-facing integration contract. Host agents make task decisions;
the engine persists scopes, evidence and execution. Transport modules do not own
classification, retrieval or file mutation behavior.

```text
src/photo_organizer/
  core/                 shared error contracts and small domain-independent helpers
  storage/              SQLite schema/migrations and no-follow filesystem IO
  library/              ingest, metadata, scan health, polling and retention
  search/               predicates, evidence evaluation, snapshots, set operations,
                        vector indexes and multi-channel retrieval
  vision/               observations, host evidence, OCR/quality, face identities,
                        legacy-compatible vision indexing and criterion review
  capabilities/         role configuration, discovery and real-input probes
    adapters/           bounded HTTP, visual and encoding protocol implementations
  organizing/           grouping proposals, naming, plans, collections and exports
  runtime/              persistent jobs, one-item actions and detached workers
  interfaces/           operation registration, JSON service, CLI and MCP transport
  cli.py                compatibility entrypoint only
  mcp_server.py         compatibility entrypoint only

tests/
  unit/                 deterministic rules, scopes, evidence and filesystem behavior
  integration/          real stdio MCP, loopback HTTP and detached worker processes
```

Dependencies flow from interfaces to domain operations and from domain operations to
storage. `core` and `storage` must not depend on transports or model integrations.
Adapter modules implement explicitly documented protocols; provider response bodies
and credentials never become error messages. Optional engines are imported only at
use, so metadata workflows do not require OCR/face/model dependencies.

`interfaces/operations.py` is registration only. Model and filesystem behavior must
remain in focused domain modules. Cross-domain coordination belongs in runtime or
a dedicated operation, not in CLI/MCP wrappers. CLI and MCP share `service.dispatch`.
New operations are discoverable through the same schema contract.

## Persistence boundaries

SQLite owns asset/file identities, root/scan revisions, immutable result memberships,
condition evidence, user corrections, group proposals, collections, plans, per-action
receipts, capability references and job checkpoints. Files under `derivatives/` are
rebuildable. Original sources are never the cache and are never deleted by cleanup.

Image vectors, description vectors and query vectors are isolated by space identity.
Host vector ingestion uses an explicit model revision. Different spaces are fused
through ranked candidates, never raw vector comparison. A result's coverage boundary
and its per-condition judgments are independent.

Group edits create successor proposals. Execution freezes the exact proposal and
member hashes. User selection is sufficient to organize selected files but does not
turn model suggestions into objective truth. A completed export returns a persistent
collection that can be selected and organized again.

## Long-running work

A detached worker owns a per-job process lock. Durable control requests stop future
item dispatch, while in-flight work completes at a safe boundary. Each item commits
independently; resume preserves completed receipts. A crashed writer's OS lock is
released; explicit recovery marks interrupted items pending and reconciles filesystem
publication before retrying. Polling has a separate singleton lock and is opt-in.

## Compatibility

The supported integration surface is versioned JSON CLI/MCP, not private Python module
paths. Legacy `python -m photo_organizer.cli` and `photo_organizer.mcp_server` remain
thin forwarding entrypoints. New internal imports use domain package paths.

## Additional contracts

`interfaces/schemas.py` owns JSON Schema; registration remains in `operations.py`.
`library/annotations.py` appends user corrections and an effective SQL view overlays
machine metadata without destroying it. `library/recipes.py` persists user-authorized
rules/preferences with optimistic revisions and explicit snapshot/dynamic semantics.
`library/imaging.py` centralizes orientation, color and alpha processing.

`runtime/context.py` exposes cooperative admission and commit hooks. Actual model POSTs
reserve durable budget immediately before dispatch; cached results and discovery GETs
do not consume model-request budget. Local computation reserves image work separately.
`capabilities/scheduling.py` uses endpoint-wide OS locks, conservative limits across
active roles, foreground waiting tickets and crash-safe slot release. Commit guards
validate bound revisions in the same write transaction as observation persistence.

`evaluation/` owns reusable metrics and kernel timing. `benchmarks/` contains executable
protocol entrypoints and host scenarios. Evaluation artifacts are evidence, not engine
configuration; independent human truth is never fabricated by a fixture.
