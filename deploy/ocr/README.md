# Local PP-OCRv5 service (Docker)

Native Linux ARM64 container for an Apple Silicon Mac. CPU inference; Docker Desktop
on macOS does not expose Metal acceleration to this Paddle runtime. No Python service
is started on the host. The container runs the official `paddlex --serve` command.

## Start / stop

From the repository root:

```sh
docker compose -f deploy/ocr/compose.yaml up -d --build
docker compose -f deploy/ocr/compose.yaml ps
docker compose -f deploy/ocr/compose.yaml logs --tail=50 ocr
curl --fail http://127.0.0.1:18080/health
```

```sh
docker compose -f deploy/ocr/compose.yaml stop
# Start again, reusing installed image and downloaded weights:
docker compose -f deploy/ocr/compose.yaml up -d
```

`down` removes this service's containers/network but retains its named model volume.
Do not add `--volumes` unless intentionally deleting the OCR model cache.
The service restarts with Docker unless explicitly stopped. It does not scan any
library or resume photo indexing. No photo directories are mounted into the container.

## Endpoint

- Local base URL: `http://127.0.0.1:18080`
- OCR: `POST /ocr`
- OpenAPI: `/openapi.json`
- Bind a different host port with `OCR_PORT=18081 docker compose -f deploy/ocr/compose.yaml up -d`.

Send a base64 image as JSON (`fileType: 1`), avoiding source file URLs. Example request:

```json
{
  "file": "BASE64_IMAGE_BYTES",
  "fileType": 1,
  "useDocUnwarping": false
}
```

The response is PaddleX's native JSON: check `errorCode == 0`, then read
`result.ocrResults[].prunedResult` for text, recognition scores, and coordinates.
Scores are model outputs, not calibrated guarantees. Numeric OCR must still be checked.

Use `./deploy/ocr/recognize.sh /absolute/image.jpg` to test via curl and jq. This is a
request client only; the long-running service is managed entirely by Docker Compose.

## Configure the photo-organizer engine

The native adapter is `paddleocr`, not the custom `photo-http` protocol:

```sh
photo-organizer --state /absolute/library-state call capability-configure --args '{"role":"ocr","config":{"protocol":"paddleocr","endpoint":"http://127.0.0.1:18080/ocr","model":"PP-OCRv5_server","revision":"paddlex-3.3.13-cpu1-v1","concurrency":1,"timeout":180}}'
```

Then call `capability-probe` with role `ocr`, an authorized `result_id`, a text-bearing
`file_id` and its known `expected_text`. Once available, run an `ocr` job over a frozen
result. The adapter disables whole-image rotation/unwarping to retain input-relative
coordinates; it returns `input_pixels_xyxy` boxes and 0..1 recognition scores. EXIF
orientation is handled by the engine; difficult rotated text may need detail review.

## Runtime and models

- Python 3.11 base inside the container.
- PaddlePaddle 3.2.2: PyPI publishes a native Linux ARM64 wheel; checked 3.3.0/3.3.1
  releases did not publish that wheel. This pin avoids silent x86 emulation.
- PaddleOCR 3.3.3 / PaddleX 3.3.13.
- PP-OCRv5_server_det and PP-OCRv5_server_rec.
- PP-LCNet document and textline orientation classifiers; document unwarping disabled.
- Official BOS model host; weights persist under `/root/.paddlex` in the Compose volume.
- Loopback-only host port, four CPU limit, 6 GiB memory limit.

### ARM64 compatibility

On this Mac's native ARM64 Docker runtime, PaddleX's default `cpu_threads: 10`
caused a segmentation fault during prediction (both CLI and HTTP). Setting only
`OMP_NUM_THREADS` was insufficient. The Dockerfile applies a checked, one-line
patch to the pinned PaddleX 3.3.13 predictor default, setting `cpu_threads: 1`.
It retains the official `paddlex --serve` entry point. OpenMP and OpenBLAS are
also limited to one thread. Recheck this workaround before upgrading PaddleX.

`pipeline.yaml` fixes model names explicitly. It does not silently switch to another
OCR generation when package defaults change. First startup downloads weights;
subsequent startups reuse the volume. Initial model download may take several minutes.

This deployment is a standalone OCR backend for later integration, not evidence that
the photo-organizer OCR adapter or a full-library OCR index has been completed.

## Local verification (2026-10-25)

- `/health` returned `errorCode: 0`; `/openapi.json` was accessible.
- Normal and 90-degree rotated Chinese/English fixtures each returned all four
  expected lines, including `AB-20261025` and `123.45`, plus scores and boxes.
  Comparison normalizes spaces and full-width colons and ignores line order;
  the rotated result had a different line order.
- Dataset photo `0951.jpg` (dense bilingual display board) returned text, with
  visible recognition noise in the output. This is an integration smoke test,
  not a ground-truth accuracy evaluation. One request took 28.48 seconds.
- Dataset photo `0001.jpg` (flower) returned no text.
- After an explicit container restart, logs confirmed reuse of all four cached
  models and another fixture request passed in 3.74 seconds.
- Compose reported healthy; the downloaded model directory occupied 179 MiB.
- Raw local evidence: `.photo-organizer/ocr-smoke/` (not public dataset additions).

These CPU timings are individual observations, not throughput benchmarks. Dense
text is substantially slower than short text. Later integration should perform
OCR during incremental indexing and search the persisted text, rather than
running OCR again on each search. Preserve raw text, confidence and geometry;
filtering and difficult-image retries belong in the indexing policy.

Sources: [PaddleOCR serving](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/inference_deployment/serving/serving.en.md),
[OCR API](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/OCR.en.md).
