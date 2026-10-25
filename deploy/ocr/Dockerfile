FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=4 \
    OPENBLAS_NUM_THREADS=4 \
    PADDLE_PDX_MODEL_SOURCE=BOS

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 update && apt-get install -y --no-install-recommends \
    libgomp1 libgl1 libglib2.0-0 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# 3.2.2 publishes a Linux ARM64 wheel; newer 3.3.x PyPI releases currently do not.
RUN pip install --no-cache-dir \
    paddlepaddle==3.2.2 \
    paddleocr==3.3.3 \
    'paddlex[ocr,serving]==3.3.13'

# PaddleX 3.3.13's CLI does not expose predictor cpu_threads. Its default of 10
# segfaults on this ARM64 runtime; OMP_NUM_THREADS alone does not override it.
# Keep the official serving CLI and narrowly patch the pinned default at build time.
RUN option_file=/usr/local/lib/python3.11/site-packages/paddlex/inference/utils/pp_option.py \
    && test "$(grep -c '\"cpu_threads\": 10,' "$option_file")" = 1 \
    && sed -i 's/"cpu_threads": 10,/"cpu_threads": 1,/' "$option_file"
ENV OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
COPY pipeline.yaml /etc/paddleocr/pipeline.yaml
EXPOSE 8080
CMD ["paddlex", "--serve", "--pipeline", "/etc/paddleocr/pipeline.yaml", "--device", "cpu", "--host", "0.0.0.0", "--port", "8080"]
