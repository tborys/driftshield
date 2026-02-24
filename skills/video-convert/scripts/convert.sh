#!/usr/bin/env bash
set -euo pipefail

# convert.sh — Convert video files to iPhone/Telegram compatible MP4.
# Part of the video-convert skill.

convert_file() {
  local input="$1"
  local output="$2"

  if [ ! -f "$input" ]; then
    echo "ERROR: input file not found: $input" >&2
    return 1
  fi

  # Check ffmpeg is available
  if ! command -v ffmpeg &>/dev/null; then
    echo "ERROR: ffmpeg not found. Install with: apt-get update && apt-get install -y ffmpeg" >&2
    return 1
  fi

  echo "Converting: $input"
  echo "       To: $output"

  ffmpeg -y -i "$input" \
    -c:v libx264 -preset medium -crf 23 \
    -c:a aac -b:a 128k \
    -pix_fmt yuv420p \
    -movflags +faststart \
    "$output" 2>&1

  local size
  size=$(du -h "$output" | cut -f1)
  echo "Done: $output ($size)"
  echo ""
}

# Batch mode
if [ "${1:-}" = "--batch" ]; then
  dir="${2:-.}"

  if [ ! -d "$dir" ]; then
    echo "ERROR: directory not found: $dir" >&2
    exit 1
  fi

  count=0
  for webm in "$dir"/*.webm; do
    [ -f "$webm" ] || continue
    mp4="${webm%.webm}.mp4"
    convert_file "$webm" "$mp4"
    count=$((count + 1))
  done

  if [ "$count" -eq 0 ]; then
    echo "No .webm files found in $dir"
    exit 0
  fi

  echo "=== Converted $count file(s) ==="
  exit 0
fi

# Single file mode
if [ $# -lt 1 ]; then
  echo "Usage:"
  echo "  $0 <input.webm> [output.mp4]"
  echo "  $0 --batch [directory]"
  exit 1
fi

input="$1"
output="${2:-${input%.webm}.mp4}"

convert_file "$input" "$output"
