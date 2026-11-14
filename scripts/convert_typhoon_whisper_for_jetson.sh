#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="typhoon-ai/typhoon-whisper-large-v3"
OUTPUT_DIR="$ROOT/models/typhoon-whisper-large-v3-ct2"
CONVERTER="${CTRANSLATE2_CONVERTER:-ct2-transformers-converter}"

if ! command -v "$CONVERTER" >/dev/null 2>&1; then
    echo "Missing $CONVERTER. Install CTranslate2, PyTorch, and Transformers in the conversion environment." >&2
    exit 1
fi

if [ -e "$OUTPUT_DIR" ]; then
    echo "Output already exists: $OUTPUT_DIR (move it aside before converting again)." >&2
    exit 1
fi

mkdir -p "$(dirname "$OUTPUT_DIR")"
"$CONVERTER" \
    --model "$MODEL" \
    --output_dir "$OUTPUT_DIR" \
    --quantization int8_float16 \
    --copy_files tokenizer.json preprocessor_config.json

if [ ! -f "$OUTPUT_DIR/model.bin" ]; then
    echo "Conversion finished without the expected model.bin: $OUTPUT_DIR" >&2
    exit 1
fi

echo "Converted Typhoon Whisper for Faster-Whisper: $OUTPUT_DIR"
