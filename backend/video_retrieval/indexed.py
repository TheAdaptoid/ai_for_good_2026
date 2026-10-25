"""Exact timestamp sampling with a metadata index and bounded window decoding."""

from bisect import bisect_left
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from .contracts import TemporalClip
from .retrieval import VideoRetriever

SAMPLER_VERSION = "pts-nearest-indexed-v1"


class IndexedTemporalSampler:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.source_stat = self._stat()
        self.times = []
        self.fallback_count = 0
        self.cancel_event = None
        self.origin = None
        with av.open(str(self.path)) as container:
            container.streams.video[0].thread_count = 2
            container.streams.video[0].thread_type = "AUTO"
            for frame in container.decode(video=0):
                absolute = self._time(frame)
                if self.origin is None:
                    self.origin = absolute
                time = absolute - self.origin
                if self.times and time <= self.times[-1]:
                    raise ValueError("Video timestamps must be strictly increasing")
                self.times.append(time)
        if not self.times:
            raise ValueError(f"No decodable frames in {self.path}")
        self.by_time = {time + self.origin: index for index, time in enumerate(self.times)}
        self._check_source()

    def _stat(self):
        stat = self.path.stat()
        return stat.st_size, stat.st_mtime_ns

    def _check_source(self):
        if self._stat() != self.source_stat:
            raise RuntimeError(f"Source video changed during processing: {self.path}")

    @staticmethod
    def _time(frame):
        if frame.pts is None or frame.time_base is None or frame.time_base <= 0:
            raise ValueError("Video frame has invalid presentation timestamps")
        return Fraction(frame.pts) * frame.time_base

    def _decode_selected(self, indices, *, seek):
        wanted = set(indices)
        last = max(wanted)
        images = {}
        with av.open(str(self.path)) as container:
            stream = container.streams.video[0]
            stream.thread_count = 2
            stream.thread_type = "AUTO"
            if seek:
                offset = int((self.origin + self.times[min(wanted)]) / stream.time_base)
                container.seek(offset, stream=stream, backward=True, any_frame=False)
            for frame in container.decode(video=0):
                if self.cancel_event is not None and self.cancel_event.is_set():
                    raise RuntimeError("Video retrieval cancelled")
                time = self._time(frame)
                index = self.by_time.get(time)
                if index is None:
                    raise RuntimeError("Decoded timestamp is absent from source index")
                if index in wanted:
                    images[index] = frame.to_ndarray(format="rgb24")
                if index >= last:
                    break
        return images

    def sample(self, *, reference_frame_number, center_seconds,
               interval_seconds=15.0, sample_count=32):
        self._check_source()
        reference = VideoRetriever._frame_index(reference_frame_number)
        count = VideoRetriever._sample_count(sample_count)
        interval = VideoRetriever._interval_seconds(interval_seconds)
        if not np.isfinite(center_seconds) or center_seconds < 0:
            raise ValueError("Center time must be finite and nonnegative")
        if reference >= len(self.times):
            raise ValueError(f"Reference frame {reference} is beyond EOF")
        center = Fraction(center_seconds)
        start, end = center - interval / 2, center + interval / 2
        targets = ([center] if count == 1 else
                   [start + i * interval / (count - 1) for i in range(count)])
        indices = []
        for target in targets:
            right = bisect_left(self.times, target)
            if right == 0:
                chosen = 0
            elif right == len(self.times):
                chosen = right - 1
            elif target - self.times[right - 1] <= self.times[right] - target:
                chosen = right - 1
            else:
                chosen = right
            indices.append(chosen)
        try:
            images = self._decode_selected(indices, seek=True)
        except (av.error.FFmpegError, RuntimeError):
            images = {}
        if set(images) != set(indices):
            self.fallback_count += 1
            images = self._decode_selected(indices, seek=False)
        if set(images) != set(indices):
            raise RuntimeError("Could not decode every indexed sample")
        self._check_source()
        return TemporalClip(
            frames=np.stack([images[index] for index in indices]),
            source_frame_indices=tuple(indices),
            source_timestamps_seconds=tuple(float(self.times[i]) for i in indices),
            target_timestamps_seconds=tuple(float(t) for t in targets),
            requested_start_seconds=float(start), requested_end_seconds=float(end),
            reference_timestamp_seconds=float(self.times[reference]),
            left_padding_count=sum(t < 0 for t in targets),
            right_padding_count=sum(t > self.times[-1] for t in targets),
        )
