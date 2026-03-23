#!/usr/bin/env bash
set -euo pipefail

# Convert HEIC images to OCR-friendly, high-fidelity PNGs.
# Usage:
#   ./test_images/convert_heic_lossless.sh [input_dir] [output_dir]
# Defaults:
#   input_dir=test_images
#   output_dir=test_images/converted_lossless

INPUT_DIR="${1:-test_images}"
OUTPUT_DIR="${2:-${INPUT_DIR%/}/converted_lossless}"

mkdir -p "$OUTPUT_DIR"

shopt -s nullglob
heic_files=("$INPUT_DIR"/*.HEIC "$INPUT_DIR"/*.heic)

if [ ${#heic_files[@]} -eq 0 ]; then
  echo "No HEIC files found in: $INPUT_DIR"
  exit 1
fi

if command -v magick >/dev/null 2>&1; then
  converter="magick"
elif command -v sips >/dev/null 2>&1; then
  converter="sips"
else
  echo "No converter found. Install ImageMagick (magick) or use macOS sips."
  exit 1
fi

echo "Converter: $converter"
echo "Input: $INPUT_DIR"
echo "Output: $OUTPUT_DIR"

for src in "${heic_files[@]}"; do
  base="$(basename "$src")"
  stem="${base%.*}"
  dst="$OUTPUT_DIR/$stem.png"

  if [ "$converter" = "magick" ]; then
    # -auto-orient applies EXIF orientation; PNG avoids further JPEG loss.
    magick "$src" -auto-orient -strip -colorspace sRGB "$dst"
  else
    # sips path on macOS (fallback).
    sips -s format png "$src" --out "$dst" >/dev/null
  fi

  dims="$(sips -g pixelWidth -g pixelHeight "$dst" 2>/dev/null | awk -F': ' '/pixelWidth|pixelHeight/{print $2}' | paste -sd'x' -)"
  echo "Converted: $src -> $dst (${dims:-unknown})"
done

echo "Done. Converted ${#heic_files[@]} file(s)."
