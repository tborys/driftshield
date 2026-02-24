---
name: video-convert
description: Convert video files to iPhone/Telegram compatible MP4 (H.264 + AAC, yuv420p, faststart). Use when asked to convert, export or prepare a video for sharing on mobile or Telegram.
---

# Video Convert

Convert `.webm` (or other video formats) to iPhone and Telegram friendly `.mp4`.

## When to use

- When asked to convert a video for mobile or Telegram
- When preparing UI walkthrough recordings for sharing
- When a `.webm` file needs to be sent to someone on iPhone
- After screen recording a demo

## How to run

### Single file

```bash
bash ~/.openclaw/workspace/skills/video-convert/scripts/convert.sh input.webm output.mp4
```

If no output path is given, it writes the `.mp4` alongside the input:

```bash
bash ~/.openclaw/workspace/skills/video-convert/scripts/convert.sh /path/to/recording.webm
# creates /path/to/recording.mp4
```

### Batch (all .webm in a directory)

```bash
bash ~/.openclaw/workspace/skills/video-convert/scripts/convert.sh --batch /path/to/dir
```

## Output format

- Video codec: H.264 (libx264)
- Audio codec: AAC 128k (no effect on silent recordings)
- Pixel format: yuv420p
- Faststart: enabled (streams without full download)
- Preset: medium, CRF 23 (good quality, small file)

## Prerequisites

ffmpeg must be installed in the container:

```bash
apt-get update && apt-get install -y ffmpeg
```

Note: this does not persist across `docker compose down && up`. If ffmpeg is missing, install it before running.

## Interpreting output

The script prints:

```
Converting: /path/to/input.webm
       To: /path/to/output.mp4
Done: /path/to/output.mp4 (152K)
```

Exit code 0 on success, 1 on failure with an error message.

## Telegram tips

- Send as document attachment to preserve quality
- Telegram accepts MP4 up to 2 GB
- Faststart flag means instant playback in chat
