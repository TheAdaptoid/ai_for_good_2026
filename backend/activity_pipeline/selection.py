import random

from .config import FrameJob


def select_frame_jobs(connection, *, video_ids=()):
    where = ""
    if video_ids:
        where = " WHERE f.video_id IN (" + ",".join("?" for _ in video_ids) + ")"
    rows = connection.execute(
        "SELECT f.frame_id,f.video_id,f.frame_number,f.source_time_seconds,MIN(d.detection_id)"
        " FROM Frame f JOIN FaceDetection d USING(frame_id)" + where +
        " GROUP BY f.frame_id,f.video_id,f.frame_number,f.source_time_seconds"
        " ORDER BY f.video_id,f.frame_number,f.frame_id", tuple(video_ids),
    )
    return [FrameJob(*row) for row in rows]


def sample_frame_jobs(population, *, sample_size=100, seed=42):
    if sample_size is not None and (isinstance(sample_size, bool) or sample_size <= 0):
        raise ValueError("sample_size must be positive")
    if not population:
        return []
    if sample_size is None:
        return list(population)
    if sample_size > len(population):
        raise ValueError(f"Sample size {sample_size} exceeds population {len(population)}")
    return sorted(random.Random(seed).sample(population, sample_size),
                  key=lambda j: (j.video_id, j.frame_number, j.frame_id))
