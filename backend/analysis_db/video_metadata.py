import json
import math
import subprocess
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path

from analysis_db.contracts import DataError, VideoMetadata

FFPROBE_TIMEOUT_SECONDS = 60


def resolve_video(filename: str, video_dir: Path) -> Path:
    if (
        not filename.strip()
        or filename in (".", "..")
        or "/" in filename
        or "\\" in filename
    ):
        raise DataError(f"video_filename must be a basename: {filename!r}")
    path = (video_dir / filename).resolve()
    if not path.is_file():
        raise DataError(f"video file does not exist: {filename!r} in {video_dir}")
    return path


def parse_probe(payload: Mapping[str, object]) -> VideoMetadata:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise DataError("ffprobe payload has no streams list")
    stream = _select_video_stream(streams)
    fmt = payload.get("format")
    fmt = fmt if isinstance(fmt, Mapping) else {}
    duration = _parse_duration(stream.get("duration"))
    if duration is None:
        duration = _parse_duration(fmt.get("duration"))
    fps = _parse_fps(stream)
    width = _parse_dimension(stream.get("width"))
    height = _parse_dimension(stream.get("height"))
    created_at = _parse_created_at(stream, fmt)
    return VideoMetadata(
        created_at=created_at,
        duration_seconds=duration,
        fps=fps,
        width=width,
        height=height,
    )


def probe_video(path: Path) -> VideoMetadata:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
    except OSError as error:
        raise DataError(f"ffprobe is not available for {path.name}: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise DataError(
            f"ffprobe timed out after {FFPROBE_TIMEOUT_SECONDS}s for {path.name}"
        ) from error
    except subprocess.CalledProcessError as error:
        stderr = (error.stderr or "").strip()
        raise DataError(
            f"ffprobe failed with status {error.returncode} for {path.name}: {stderr or error}"
        ) from error
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise DataError(f"ffprobe returned invalid JSON for {path.name}: {error}") from error
    if not isinstance(payload, dict):
        raise DataError(f"ffprobe returned non-object JSON for {path.name}")
    return parse_probe(payload)


def _select_video_stream(streams: list[object]) -> Mapping[str, object]:
    for stream in streams:
        if not isinstance(stream, Mapping):
            continue
        if stream.get("codec_type") != "video":
            continue
        disposition = stream.get("disposition")
        attached_pic = (
            disposition.get("attached_pic")
            if isinstance(disposition, Mapping)
            else None
        )
        if attached_pic == 1:
            continue
        return stream
    raise DataError("ffprobe payload has no usable video stream")


def _parse_finite_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _parse_duration(value: object) -> float | None:
    number = _parse_finite_float(value)
    if number is None or number < 0:
        return None
    return number


def _parse_fps(stream: Mapping[str, object]) -> float | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        fps = _rational_to_float(stream.get(key))
        if fps is not None and fps > 0:
            return fps
    return None


def _rational_to_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        fps = float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError, OverflowError, ArithmeticError):
        return None
    if not math.isfinite(fps):
        return None
    return fps


def _parse_dimension(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None


def _parse_created_at(
    stream: Mapping[str, object], fmt: Mapping[str, object]
) -> str | None:
    for mapping in (stream, fmt):
        tags = mapping.get("tags")
        if not isinstance(tags, Mapping):
            continue
        value = tags.get("creation_time")
        if isinstance(value, str) and value.strip():
            return value
    return None
