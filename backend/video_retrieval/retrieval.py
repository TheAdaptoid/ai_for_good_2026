from contextlib import closing
from fractions import Fraction
import math
import operator
from pathlib import Path

import av
import numpy as np

from analysis_db.paths import DEFAULT_DB, REPOSITORY_ROOT
from analysis_db.storage import connect_database
from .contracts import DetectionInfo, TemporalClip


class _TemporalValidationError(ValueError):
    pass


class VideoRetriever:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(DEFAULT_DB if db_path is None else db_path).resolve()
        with closing(connect_database(self.db_path, read_only=True)):
            pass

    def get_detection_info(self, detection_id: int) -> DetectionInfo:
        with closing(connect_database(self.db_path, read_only=True)) as connection:
            row = connection.execute(
                "SELECT d.detection_id, d.person_id, f.video_id, f.frame_id,"
                " f.frame_number, f.source_time_seconds, d.x1, d.y1, d.x2, d.y2"
                " FROM FaceDetection AS d JOIN Frame AS f ON f.frame_id = d.frame_id"
                " WHERE d.detection_id = ?",
                (detection_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Detection {detection_id} does not exist")
        return DetectionInfo(
            detection_id=int(row[0]),
            person_id=str(row[1]),
            video_id=int(row[2]),
            frame_id=str(row[3]),
            frame_number=int(row[4]),
            source_time_seconds=float(row[5]),
            bbox=(float(row[6]), float(row[7]), float(row[8]), float(row[9])),
        )

    def get_frame(self, video_id: int, frame_number: int) -> np.ndarray:
        """Return an original RGB frame by zero-based presentation-order index."""
        frame_number = self._frame_index(frame_number)
        path = self._video_path(video_id)
        return self._decode_window(path, frame_number, frame_number, frame_number)[0]

    def get_face(self, detection_id: int) -> np.ndarray:
        """Return the unresized crop using outward-rounded, clamped bounds."""
        info = self.get_detection_info(detection_id)
        x1, y1, x2, y2 = info.bbox
        if not all(math.isfinite(value) for value in info.bbox):
            raise ValueError(f"Detection {detection_id} has non-finite crop bounds")
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Detection {detection_id} has empty crop bounds")
        image = self.get_frame(info.video_id, info.frame_number)
        height, width = image.shape[:2]
        left = max(0, min(width, math.floor(x1)))
        top = max(0, min(height, math.floor(y1)))
        right = max(0, min(width, math.ceil(x2)))
        bottom = max(0, min(height, math.ceil(y2)))
        if right <= left or bottom <= top:
            raise ValueError(f"Detection {detection_id} has an empty crop after clamping")
        return image[top:bottom, left:right].copy()

    def get_clip(self, detection_id: int) -> np.ndarray:
        """Return 32 RGB frames with the reference at slot 16 and edge repeats."""
        info = self.get_detection_info(detection_id)
        reference = self._frame_index(info.frame_number)
        path = self._video_path(info.video_id)
        return self._decode_window(path, reference - 16, reference + 15, reference)

    def get_temporal_clip(
        self, detection_id: int, interval_seconds: float, sample_count: int = 32,
    ) -> TemporalClip:
        info = self.get_detection_info(detection_id)
        reference = self._frame_index(info.frame_number)
        path = self._video_path(info.video_id)
        return self._decode_temporal_window(
            path, reference, info.source_time_seconds,
            interval_seconds, sample_count,
        )

    def _video_path(self, video_id: int) -> Path:
        with closing(connect_database(self.db_path, read_only=True)) as connection:
            row = connection.execute(
                "SELECT file_path FROM Video WHERE video_id = ?", (video_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Video {video_id} does not exist")
        path = (REPOSITORY_ROOT / Path(row[0])).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Original video {video_id} is unavailable: {path}")
        return path

    @staticmethod
    def _frame_index(frame_number: int) -> int:
        try:
            index = operator.index(frame_number)
        except TypeError as exc:
            raise ValueError(f"Frame index must be an integer: {frame_number!r}") from exc
        if index < 0:
            raise ValueError(f"Frame index must be nonnegative: {index}")
        return index

    @staticmethod
    def _decode_window(path: Path, start: int, end: int, reference: int) -> np.ndarray:
        output = None
        filled = 0
        last_index = -1
        count = end - start + 1
        try:
            with av.open(str(path)) as video:
                for last_index, frame in enumerate(video.decode(video=0)):
                    if last_index < max(0, start):
                        continue
                    image = frame.to_ndarray(format="rgb24")
                    if output is None:
                        output = np.empty((count, *image.shape), dtype=np.uint8)
                    stop = min(count, last_index - start + 1)
                    # On frame zero this also fills any left-edge padding.
                    output[filled:stop] = image
                    filled = stop
                    del image
                    if last_index >= end:
                        break
        except Exception as exc:
            raise RuntimeError(
                f"Failed to decode video {path} for reference frame {reference}"
                f" (window {start}..{end}): {exc}"
            ) from exc

        # Validate the reference before filling the right edge: padding must not
        # disguise a database frame number that is beyond the actual video.
        if last_index < reference or output is None:
            raise ValueError(
                f"Frame {reference} is beyond EOF in {path}"
                f" ({last_index + 1} frames decoded)"
            )
        if filled < count:
            output[filled:] = output[filled - 1]
        return output

    @staticmethod
    def _sample_count(sample_count: object) -> int:
        if isinstance(sample_count, bool):
            raise ValueError(f"sample_count must be an integer: {sample_count!r}")
        try:
            count = operator.index(sample_count)
        except TypeError as exc:
            raise ValueError(
                f"sample_count must be an integer: {sample_count!r}"
            ) from exc
        if count < 1:
            raise ValueError(f"sample_count must be positive: {count}")
        return count

    @staticmethod
    def _interval_seconds(interval_seconds: object) -> Fraction:
        if isinstance(interval_seconds, bool):
            raise ValueError(
                "interval_seconds must be a finite positive number:"
                f" {interval_seconds!r}"
            )
        try:
            finite = math.isfinite(interval_seconds)
        except TypeError as exc:
            raise ValueError(
                "interval_seconds must be a finite positive number:"
                f" {interval_seconds!r}"
            ) from exc
        if not finite:
            raise ValueError(
                "interval_seconds must be a finite positive number:"
                f" {interval_seconds!r}"
            )
        if interval_seconds <= 0:
            raise ValueError(
                "interval_seconds must be a finite positive number:"
                f" {interval_seconds!r}"
            )
        return Fraction(interval_seconds)

    def _decode_temporal_window(
        self, path: Path, reference: int, center: float,
        interval_seconds: float, sample_count: int,
    ) -> TemporalClip:
        count = self._sample_count(sample_count)
        interval = self._interval_seconds(interval_seconds)
        if not math.isfinite(center):
            raise ValueError(
                f"Detection reference has a non-finite source time: {center!r}"
            )
        if center < 0:
            raise ValueError(
                f"Detection reference has a negative source time: {center!r}"
            )
        center_time = Fraction(center)
        half = interval / 2
        start = center_time - half
        end = center_time + half
        if count == 1:
            targets = [center_time]
        else:
            step = (end - start) / (count - 1)
            targets = [start + index * step for index in range(count)]

        pending = 0
        output = None
        cached = [None, None]
        previous = None
        slot_indices: list[int] = []
        slot_times: list[Fraction] = []
        decoded_frames = 0
        origin = None
        reference_time = None
        final = None

        def chosen_image(chosen):
            nonlocal output
            frame = chosen[0]
            if cached[0] is not frame:
                cached[0] = frame
                cached[1] = frame.to_ndarray(format="rgb24")
            if output is None:
                output = np.empty((count, *cached[1].shape), dtype=np.uint8)
            return cached[1]

        try:
            with av.open(str(path)) as video:
                for index, frame in enumerate(video.decode(video=0)):
                    if (frame.pts is None or frame.time_base is None
                            or frame.time_base <= 0):
                        raise _TemporalValidationError(
                            f"Frame {index} in {path} has invalid timestamps:"
                            f" pts {frame.pts!r}, time base {frame.time_base}"
                        )
                    time = Fraction(frame.pts) * frame.time_base
                    if decoded_frames == 0:
                        origin = time
                        time = Fraction(0)
                    else:
                        time -= origin
                        if time <= previous[1]:
                            raise _TemporalValidationError(
                                f"Video {path} has nonincreasing timestamps at"
                                f" frame {index}: {float(time)} after"
                                f" {float(previous[1])}"
                            )
                    current = (frame, time, index)
                    while pending < count and targets[pending] <= time:
                        target = targets[pending]
                        if previous is None:
                            chosen = current
                        else:
                            choose_previous = target - previous[1] <= time - target
                            chosen = previous if choose_previous else current
                        slot_indices.append(chosen[2])
                        slot_times.append(chosen[1])
                        output[pending] = chosen_image(chosen)
                        pending += 1
                    previous = current
                    if cached[0] is not current[0]:
                        cached[0] = cached[1] = None
                    decoded_frames += 1
                    final = current
                    if index == reference:
                        reference_time = time
        except _TemporalValidationError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to decode video {path} for reference frame {reference}"
                f" ({count} temporal samples): {exc}"
            ) from exc

        if decoded_frames == 0:
            raise ValueError(f"Video {path} contains no decodable frames")
        if reference_time is None:
            raise ValueError(
                f"Frame {reference} is beyond EOF in {path}"
                f" ({decoded_frames} frames decoded)"
            )
        while pending < count:
            slot_indices.append(final[2])
            slot_times.append(final[1])
            output[pending] = chosen_image(final)
            pending += 1
        left_padding = sum(1 for target in targets if target < 0)
        right_padding = sum(1 for target in targets if target > final[1])
        return TemporalClip(
            frames=output,
            source_frame_indices=tuple(slot_indices),
            source_timestamps_seconds=tuple(
                float(value) for value in slot_times
            ),
            target_timestamps_seconds=tuple(
                float(value) for value in targets
            ),
            requested_start_seconds=float(start),
            requested_end_seconds=float(end),
            reference_timestamp_seconds=float(reference_time),
            left_padding_count=left_padding,
            right_padding_count=right_padding,
        )
