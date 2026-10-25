#!/bin/sh
set -eu
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "Usage: $0 /absolute/image.jpg" >&2
  exit 2
fi
command -v jq >/dev/null || { echo 'jq is required' >&2; exit 2; }
ocr_tmp=$(mktemp -d)
trap 'rm -rf "$ocr_tmp"' EXIT HUP INT TERM
base64 < "$1" | tr -d '\n\r' > "$ocr_tmp/image.b64"
jq -n --rawfile image "$ocr_tmp/image.b64" '{file:$image,fileType:1,useDocUnwarping:false}' > "$ocr_tmp/request.json"
curl --fail-with-body --silent --show-error --max-time 180 \
  -H 'Content-Type: application/json' \
  --data-binary "@$ocr_tmp/request.json" \
  "http://127.0.0.1:${OCR_PORT:-18080}/ocr" > "$ocr_tmp/response.json"
jq -e 'if .errorCode == 0 then {errorCode,errorMsg,results:[.result.ocrResults[].prunedResult]} else error(.errorMsg) end' "$ocr_tmp/response.json"
