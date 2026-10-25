# Delivery and release evidence

Date: 2026-10-25. Development target: PRD v0.7. Candidate: 0.2.0a3.
The portable Skill and engine implementation is ready for user integration testing.
This is an alpha development delivery, not a completed model-quality or community
release acceptance. No model downloads or real-library inference were performed in
this development batch.

## Implementation traceability

| PRD contract | Implementation | Development evidence |
| --- | --- | --- |
| 3.1 portable Skill and text-only hosts | Shared CLI/MCP service, JSON Schema discovery/validation, native MCP image, external vision/OCR/vector/face roles | Real stdio workflow, schema and HTTP fixtures |
| 4.E–G free composition and refinement | Immutable results, explicit selections, ordering, set algebra, lineage, recipes and editable preferences | Composition, scope, dynamic-vs-frozen and stale-selection tests |
| 5.1–5.4 indexing and retrieval | Metadata, image/description spaces, OCR/text, vector/reference search, RRF, coverage ledger | Separate-space/partial-coverage/caching tests; no quality claim |
| 5.5–5.9 configuration | Per-role adapters, real-input probes, credential references, host submission, explicit fallback and detail escalation | Loopback modality/auth/rate/error tests; real vendors require acceptance |
| 5.10 lifecycle | Migrations, stable rename identity, offline roots, atomic scan commit, scan checkpoints, source-change rejection, watcher and retention | Offline/partial-scan/interruption/recovery tests |
| 5.11 evidence and corrections | Unknown/unanalyzed states, exact-criterion evidence, frozen evidence metadata, scoped corrections, user metadata overlay | Boolean, evidence lineage and correction tests |
| 6/6.1 deterministic organization | Nested editable groups, overlap policy, naming, date basis, collision preflight, receipts and reusable collections | Filesystem, export, grouping, pagination and no-clobber tests |
| 7 preprocessing | Decoded format, EXIF orientation, ICC-to-sRGB, transparency, bounded detail crops and validated JPEG output | Color/alpha/crop/export tests |
| 8.1 durable runtime | Cross-process provider slots, interactive priority, cache-aware reservations, missing-role binding, pause/cancel/recover, Retry-After, late-result guard | Multiprocess admission, controls, retries, crash reservation and configuration-race tests |
| 9 evaluation support | Full-scope truth scorer, per-group metrics/gates, cached-kernel timing, host trace harness | Scoring regression tests; actual acceptance measurements pending |

## Verification

- 66 local regression tests pass, including real MCP image/stdio transport, loopback
  HTTP and cross-process workers. Ruff lint/format and Skill validation pass.
- Wheel and source archive build successfully. The wheel installs outside the checkout
  in a fresh virtual environment, includes the Skill, and passes the same 66 tests.
  `benchmarks/results/package-smoke.json` records the isolated installation output.
- Linux/macOS × Python 3.11/3.13 passed remotely for implementation commit `61ba8f4`.
  Later candidate commits must have their own CI results; an earlier pass does not
  certify a changed revision.
- Deterministic fixtures establish engineering behavior. They do not establish semantic
  recall, Chinese model quality, face identity accuracy or user preference satisfaction.

## User and release acceptance remaining

- Configure the actual intended endpoints/models and run the nine PRD capability
  scenarios, including a text-only host and mixed providers.
- Run the same task chains through two independent agent hosts, restart/resume and
  missing-capability recovery. The SDK integration client is not a second host.
- Collect independent full-scope labels and execute the held-out quality protocol,
  face-specific dataset and subjective user review. See [EVALUATION.md](EVALUATION.md).
- Measure the real library, model/hardware latency, background contention, complete-scope
  accounting and file throughput; 10,000-photo support remains unmeasured.

These acceptance items require actual host/model/data evidence and are not open promises
of unimplemented endpoints. Any failures found in acceptance must be fixed before a
release claim.

## Explicit product limits

POSIX only (Linux/macOS); Windows is unsupported. No original-file move/delete, automatic
file rollback, arbitrary provider protocol compatibility, RAW/Live Photo completeness,
cloud-drive adapter or display UI is claimed. These follow the PRD's scope boundary.
Provider queue priority is local admission, not preemption of a vendor's in-flight work.
Monetary bounds use the caller's conservative per-request estimate, not an exact bill.
A dynamic recipe is refreshed explicitly, never silently substituted for a frozen result.
