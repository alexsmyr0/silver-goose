"""Read ingredient media facts. No publishing/provider policy or file conversion."""

import json, math, os, subprocess


def inspect(path):
    if not os.path.isfile(path) or not os.path.getsize(path):
        raise ValueError(
            "This media file is missing or empty: " + os.path.basename(path)
        )
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        raise ValueError("Could not read media: " + os.path.basename(path))
    try:
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        video = next(
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not s.get("disposition", {}).get("attached_pic")
        )
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        duration = float(
            data.get("format", {}).get("duration") or video.get("duration")
        )
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError()
    except (ValueError, TypeError, StopIteration):
        raise ValueError("This file has no readable video: " + os.path.basename(path))
    return dict(video=video, audio=audio, duration=duration, size=os.path.getsize(path))
