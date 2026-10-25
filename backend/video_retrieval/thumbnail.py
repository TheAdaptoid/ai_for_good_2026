"""Small JPEG previews decoded on request. Nothing is written to disk."""

import io
from pathlib import Path

import av


def frame_jpeg(path: Path, seconds: float, *, size: tuple[int, int] = (320, 180)) -> bytes:
    """Return the first frame at or after ``seconds`` as a JPEG no larger than ``size``."""
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        container.seek(int(max(seconds, 0) / stream.time_base), stream=stream, backward=True)
        frame = None
        for frame in container.decode(stream):
            if frame.time is not None and frame.time >= seconds:
                break
        if frame is None:
            raise LookupError(f"no video frame at {seconds} s in {path.name}")
        image = frame.to_image()
    image.thumbnail(size)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=70)
    return out.getvalue()
