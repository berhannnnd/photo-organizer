# Reproducible quality and performance evaluation

Implementation checks do not establish model quality. Use PRD §9.5 as the acceptance
protocol. Freeze the dataset hashes, duplicate/near-duplicate grouping, split, query
set, provider/model revision, preprocessing, hardware and run identity before testing.
Keep related duplicate groups in one split. Use the prescribed 200/300/500 division
only when the actual groups permit it; report deviations instead of leaking holdout
images into development. Do not tune against the held-out report.

## Full-scope truth and ranking

`benchmarks/quality_protocol.py --truth TRUTH.json --predictions RANKINGS.json --output REPORT.json`
reads only the supplied artifacts and never calls a model. Truth format:

```json
{
  "scope_hashes": ["sha256-A", "sha256-B", "sha256-C"],
  "annotation_source": "independent_human",
  "disputes_reviewed": true,
  "queries": [{
    "id": "subject-01",
    "group": "subject",
    "text": "a cat",
    "labels": {"sha256-A": "yes", "sha256-B": "no", "sha256-C": "disputed"}
  }]
}
```

Rankings map each query ID to ordered content hashes, e.g.
`{"subject-01": ["sha256-B", "sha256-A"]}`. Missing predictions are empty results,
not excluded measurements. Every query requires labels for the entire frozen scope;
labeling only retrieved photos is rejected. Duplicate predictions are counted and
collapsed by content. Disputed truth is reported explicitly. Unreturned positives,
including unknown/unanalyzed results, count as false negatives. Zero-prediction
precision is null, never 100%.

Reports include TP/FP/FN, precision/recall, recall@10/50, per-group macro/micro and
input artifact digests. The formal gate requires at least 300 scoped contents and
10 queries in each of `subject`, `scene_attribute`, `boolean_count`, `paraphrase`,
`example`, `relation`. Common-subject queries require at least 20 positives and
95% precision/90% recall; other groups require 90%/85%. Insufficient evidence and
model-assisted annotations return `unmeasured`, never a quality pass. Subjective
acceptance and face identity benchmarks require their separate user-reviewed data.

## Retrieval kernel

`benchmarks/kernel_protocol.py --state STATE --cases CASES.json --output REPORT.json`
uses cached query vectors, so it makes no model calls. Cases are a JSON list of
`vector-search` arguments, for example:

```json
[{"space_id":"SPACE_ID","text":"cat","parent_id":"FROZEN_SCOPE","top_k":50}]
```

At least 20 distinct queries and 10 repetitions are required for its gate. The
report includes every duration and failure, success rate, p95, runtime and platform.
It creates result snapshots in the chosen catalog; use an isolated catalog copy for
benchmark work. Run the same cases idle and with background indexing, preserving
both raw reports. This kernel timer does not claim embedding, network or agent latency.

Cold model load, warm uncached-query encoding, cached encoding, background contention,
plan/apply timing and file throughput must be measured separately under PRD §9.5.
`benchmarks/scenarios.json`, `glm_skill_agent.py` and `audit_scenarios.py` support
host trace collection and file verification. SDK transport tests are not independent
agent-host acceptance; run the required task chains in each actual target host.
