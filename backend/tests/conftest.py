from dataclasses import replace
import pytest
from analysis_db.contracts import DetectionRow


@pytest.fixture
def make_row():
    base = DetectionRow(2, "Clip", "clip.mp4", 0, "frame-0", "person-1",
                        0.0, 1.0, 2.0, 10.0, 20.0, 0.9)
    return lambda **changes: replace(base, **changes)
