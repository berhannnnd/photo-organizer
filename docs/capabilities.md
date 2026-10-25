# Capability setup and transport contracts

The Skill's host can be text-only. Configure roles independently through
`call capability-configure --args '{"role":"vision","config":{...}}'`, then
`capability-probe` with an authorized result ID and file ID. `capability-status`
reports configuration, probe evidence and missing roles. A successful probe establishes
real input handling, not photo-library accuracy. No weights or credentials are discovered
or downloaded automatically.

## Implemented adapters

| Role | Protocol | Endpoint / local requirements |
| --- | --- | --- |
| vision | anthropic | Full messages URL; HTTPS remotely |
| vision | openai | Full chat-completions URL with image content support |
| vision | ollama | Base URL; installed vision model; `/api/chat` |
| image_text | ollama | Base URL; installed multimodal embedding artifact; `/api/embed` |
| image_text | photo-http | Full custom endpoint implementing the contract below |
| description_text | openai-text | Full text embeddings URL; explicit model revision |
| description_text | ollama / photo-http | Matching text query and description encoder |
| ocr | tesseract | Installed `tesseract` executable and language data, default `eng` |
| ocr | vision | Uses the separately configured and verified vision role |
| ocr | photo-http | Full custom endpoint |
| faces | opencv | Optional `opencv-python`, installed YuNet detector and SFace recognizer paths |
| faces | photo-http | Full custom endpoint and explicit feature space |
| host-supplied observation | host | Host reads images and submits scoped observations; declaration alone is not verification |

Configuration accepts `protocol`, `endpoint`, `model`, `revision`, `space`,
`api_key_env`, `timeout` (1–300 seconds), `concurrency` (1–8), `language`,
`detector_path`, `recognizer_path` as applicable. Use environment references for
secrets. Loopback HTTP is supported for local services; remote endpoints require
HTTPS. Redirects are refused to avoid forwarding credentials. Some providers need
an explicit compatible adapter; an arbitrary URL does not establish compatibility.

Examples (replace paths/models with ones actually available):

```json
{"role":"vision","config":{"protocol":"openai","endpoint":"https://provider.example/v1/chat/completions","model":"IMAGE_CAPABLE_MODEL","api_key_env":"PHOTO_VISION_KEY"}}
```

```json
{"role":"ocr","config":{"protocol":"tesseract","language":"eng"}}
```

```json
{"role":"image_text","config":{"protocol":"ollama","endpoint":"http://127.0.0.1:11434","model":"INSTALLED_MULTIMODAL_EMBEDDING_MODEL"}}
```

```json
{"role":"faces","config":{"protocol":"opencv","detector_path":"/absolute/yunet.onnx","recognizer_path":"/absolute/sface.onnx"}}
```

A probe requires `role`, `result_id`, `file_id`; OCR also requires `expected_text`.
Text-only encoding needs `text` instead of a photo. Use an authorized fixture to
avoid unexpectedly sending private images. API configuration does not change the
host chat model. Configuration changes invalidate the role's verification; running
jobs keep their original revision and stop on changes.

## photo-http adapter (explicit custom protocol)

This is a documented integration protocol, not a claim that arbitrary vendor APIs
use this shape. The configured endpoint receives JSON and returns JSON:

- Embedding request: `{operation: "embed", model, input: "text"}` or
  `{operation: "embed", model, input: {image: "BASE64_JPEG"}}`.
  Response: `{space: "CONFIGURED_SPACE", embeddings: [[finite numbers]]}`.
  Exactly one nonzero vector. Image/query encoders must share the same space;
  matching dimension alone is insufficient. Configure immutable `revision`.
- OCR request: `{operation: "ocr", model, image: "BASE64_JPEG"}`.
  Response: `{text: "...", regions: [], coordinate_system: "..."}`.
- Faces request: `{operation: "faces", model, image: "BASE64_JPEG"}`.
  Response: `{space: "CONFIGURED_SPACE", faces: [{box: [x,y,width,height], vector: [...]}]}`.
  Coordinates refer to the input image; features are normalized and isolated by space.

## Durable work

`job-start(operation, arguments, budget, background=true)` snapshots members and
returns immediately. Operations: `index`, `review`, `embed`, `ocr`, `quality`,
`faces`, `scan`, `apply`. Analysis operations require `result_id`; review also
requires `condition`; scan requires `root`; apply requires `plan_id`.

Use `job-status`, `job-control` (`pause`, `cancel`, `resume`, `retry`), and
`job-recover` for an interrupted worker whose process lock is no longer held.
Controls acknowledge before an in-flight call finishes. Completed items remain
journaled. Configuration changes require explicit `rebind:true` when resuming;
model items are reevaluated under the new revision. There is no silent service switch.

Budgets: `max_images`, `max_requests`, `max_seconds`. Monetary caps require an
explicit conservative `max_request_cost`; actual billing remains provider-dependent.
Unknown price must not be presented as exact cost control. Reservations are persisted
before dispatch. Analysis is sequential per worker; concurrent processes are bounded
by stage locks and provider scheduling. Transient errors have at most two extra retries.

`roots` reports scan health. `watch(action="start", interval=30)` enables an
opt-in polling reconciler; `stop` disables it. This is not instantaneous event delivery.
Offline roots retain their indexes and old snapshots; ordinary searches exclude them.
`cache-cleanup` defaults to dry-run and retains original photos, referenced results and
plans. Unreferenced derivatives get a retention window before removal.
