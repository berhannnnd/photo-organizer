# Contributing

The repository is in development alpha. `docs/PRD.md` is the product target;
`docs/DELIVERY.md` records what is actually implemented and validated. Early `DESIGN.md`
is historical context, not the current contract.

Keep responsibilities separate: transport adapters call `service.py`; predicates,
result snapshots, catalog, preprocessing, providers, planning and file execution own
their respective behavior. Do not add phrase-specific branches for subjective queries.

Before submitting a change:

- Add behavioral tests for changed invariants, particularly scope inheritance,
  uncertain evidence, stale source detection, no-clobber execution and recovery.
- Run `python -m unittest discover -s tests -v`; use `.[mcp,dev]` for the complete suite.
- Build the wheel and sdist. Keep the portable Skill's actual supported interface aligned.
- Update the changelog and capability limitations when behavior changes.
- Do not commit credentials, personal photos, model outputs containing private data,
  local databases, downloaded models or generated packages.

Live model tests are opt-in and must name the exact model artifact and provider.
Mock tests, transport integration, independent host acceptance, semantic quality and
performance benchmarks are distinct evidence. Do not infer one from another.

Code contributions are distributed under the repository MIT license. Photo datasets
retain their own source licenses and are not bundled.
