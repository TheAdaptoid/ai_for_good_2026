from itertools import count

import cv2
import numpy as np
import pytest


@pytest.fixture
def make_video(tmp_path):
    names = count()

    def make(*, frames=60, size=(96, 64)):
        path = tmp_path / f"video-{next(names)}.avi"
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, size
        )
        try:
            assert writer.isOpened(), "MJPG video writer is unavailable"
            frame = np.full((size[1], size[0], 3), (0, 0, 255), dtype=np.uint8)
            for _ in range(frames):
                writer.write(frame)
        finally:
            writer.release()
        return path

    return make
