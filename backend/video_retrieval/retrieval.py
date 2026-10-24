from contextlib import closing
import math
import operator
from pathlib import Path

import av
import numpy as np

from analysis_db.paths import DEFAULT_DB, REPOSITORY_ROOT
from analysis_db.storage import connect_database
from .contracts import DetectionInfo


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
