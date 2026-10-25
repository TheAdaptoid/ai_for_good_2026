"""In-memory frame windows for activity inference. Frames are never written to disk.

Seeks to the keyframe before each window and decodes forward, instead of decoding from the start
of the video for every request (unusable for a two-hour video).
"""

from collections.abc import Iterator, Sequence
from pathlib import Path

import av
import numpy as np


def _scaled_size(width: int, height: int, short_side: int) -> tuple[int, int]:
    if min(width, height) <= short_side:
        return width, height
    scale = short_side / min(width, height)
    # Even dimensions keep swscale happy for every pixel format.
    return max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2)


def read_windows(path: Path, fps: float, windows: Sequence[Sequence[int]], *,
                 short_side: int = 224) -> Iterator[np.ndarray]:
    """Yield one (T, H, W, 3) uint8 RGB array per window of zero-based frame indices, in order.

    Frame index = round((frame time - stream start) x fps). A requested index the decoder never
    produced (dropped or duplicate timestamps) takes the nearest decoded frame.
    """
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        base = float(stream.time_base)
        start_pts = stream.start_time or 0
        width, height = _scaled_size(stream.codec_context.width, stream.codec_context.height,
                                     short_side)
        for indices in windows:
            wanted = set(indices)
            first, last = min(wanted), max(wanted)
            # Aim a little early so a timestamp rounding never lands the seek past `first`.
            target = max(0.0, (first - 1) / fps)
            container.seek(start_pts + int(target / base), stream=stream, backward=True,
                           any_frame=False)
            got: dict[int, np.ndarray] = {}
            for frame in container.decode(stream):
                if frame.pts is None:
                    continue
                index = round((frame.pts - start_pts) * base * fps)
                if index > last:
                    break
                if index in wanted:
                    got[index] = frame.reformat(width=width, height=height,
                                                format="rgb24").to_ndarray()
            if not got:
                raise RuntimeError(f"could not decode frames {first}-{last} from {path.name}")
            keys = sorted(got)
            yield np.stack([got[min(keys, key=lambda k: (abs(k - i), k))] for i in indices])
