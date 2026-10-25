"""Validated, transactional persistence of frame-linked model results."""

from dataclasses import asdict
import hashlib
import json
import math
import os

from analysis_db.contracts import DataError


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def config_fingerprint(settings):
    return hashlib.sha256(canonical_json(settings).encode("utf-8")).hexdigest()


def input_metadata(job, *, video_path, repository_root, stat=None):
    stat = video_path.stat() if stat is None else stat
    return {"frame_id":job.frame_id,"video_id":job.video_id,
            "frame_number":job.frame_number,"source_time_seconds":job.source_time_seconds,
            "video_path":os.path.relpath(video_path, repository_root),
            "size":stat.st_size,"mtime_ns":stat.st_mtime_ns}


def input_fingerprint(job, *, video_path, repository_root, stat=None):
    return config_fingerprint(input_metadata(job, video_path=video_path,
                                             repository_root=repository_root,stat=stat))


def result_matches(connection, frame_id, config_hash, input_hash):
    return connection.execute(
        "SELECT 1 FROM Activity WHERE frame_id=? AND config_hash=? AND input_hash=?",
        (frame_id, config_hash, input_hash)).fetchone() is not None


def save_activity(connection, job, sampling, result, *, config_json, config_hash,
                  input_hash, retrieval_time_seconds):
    if connection.in_transaction:
        raise DataError("Activity persistence requires an idle connection")
    if result.num_frames != 32 or not result.predictions:
        raise ValueError("Activity requires 32 samples and nonempty predictions")
    for key in ("source_frame_indices", "source_timestamps_seconds", "target_timestamps_seconds"):
        if len(sampling[key]) != 32:
            raise ValueError(f"Expected 32 entries in {key}")
    if sampling["requested_end_seconds"] <= sampling["requested_start_seconds"]:
        raise ValueError("Activity window must have positive duration")
    if not math.isfinite(retrieval_time_seconds) or retrieval_time_seconds < 0:
        raise ValueError("Retrieval time must be finite and nonnegative")
    for prediction in result.predictions:
        if not prediction.label.strip() or not 0 <= prediction.score <= 1:
            raise ValueError("Activity labels and scores are invalid")
    result_json = canonical_json(asdict(result))
    payload = dict(sampling, retrieval_time_seconds=retrieval_time_seconds)
    sampling_json = canonical_json(payload)
    if config_fingerprint(json.loads(config_json)) != config_hash:
        raise ValueError("Configuration hash does not match stored configuration")
    top = result.predictions[0]
    values = (job.frame_id, sampling["requested_start_seconds"], sampling["requested_end_seconds"],
              32, top.label, top.score, result_json, sampling_json, config_json, config_hash, input_hash)
    columns = ("frame_id", "window_start_seconds", "window_end_seconds", "sample_count",
               "activity_label", "score", "result_json", "sampling_json", "config_json", "config_hash", "input_hash")
    connection.execute("BEGIN IMMEDIATE")
    try:
        actual = connection.execute("SELECT video_id,frame_number,source_time_seconds FROM Frame WHERE frame_id=?",
                                    (job.frame_id,)).fetchone()
        if actual != (job.video_id, job.frame_number, job.source_time_seconds):
            raise DataError("Center frame changed during activity processing")
        update = ",".join(f"{name}=excluded.{name}" for name in columns[1:])
        connection.execute(
            f"INSERT INTO Activity ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
            f" ON CONFLICT(frame_id) DO UPDATE SET {update},"
            "created_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')", values)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
