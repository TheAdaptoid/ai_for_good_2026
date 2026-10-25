from dataclasses import fields
import json

import pytest

from activity_classification.contracts import ActivityPrediction, ClassificationResult
from activity_classification.runtime import MODEL_ID, MODEL_REVISION
from activity_pipeline.selection import select_frame_jobs
from analysis_db.activity_results import canonical_json, config_fingerprint, save_activity
from analysis_db.storage import connect_database
from video_retrieval.indexed import IndexedTemporalSampler


@pytest.mark.parametrize("score,expected", [
    (0.64, "Uncertain result"),
    (0.65, "Uncertain result"),
    (0.650001, "Speaking"),
    (0.90, "Speaking"),
])
def test_activity_label_is_automatically_decided_at_save(video, score, expected):
    connection = connect_database(video.db_path)
    try:
        job = select_frame_jobs(connection)[0]
        clip = IndexedTemporalSampler(video.video_path).sample(
            reference_frame_number=job.frame_number, center_seconds=job.source_time_seconds)
        sampling = {f.name:getattr(clip,f.name) for f in fields(clip) if f.name != "frames"}
        result = ClassificationResult(
            predictions=(ActivityPrediction("Speaking", "People speaking.", 2.0, score),
                         ActivityPrediction("Acting", "People acting.", 1.0, 1 - score)),
            model=MODEL_ID, model_revision=MODEL_REVISION, device="cpu", dtype="torch.float32",
            input_frame_count=32, num_frames=32, selected_frame_indices=tuple(range(32)),
            score_type="candidate_relative_softmax", preprocessing_time_seconds=0.1,
            inference_time_seconds=0.2, total_time_seconds=0.3,
            peak_gpu_memory_allocated_mib=None, peak_gpu_memory_reserved_mib=None)
        config = {"decision_policy":{"min_score_exclusive":0.65,"uncertain_label":"Uncertain result"}}
        save_activity(connection, job, sampling, result, config_json=canonical_json(config),
                      config_hash=config_fingerprint(config), input_hash="source",
                      retrieval_time_seconds=0.1)
        label, saved_score, raw = connection.execute(
            "SELECT activity_label,score,result_json FROM Activity").fetchone()
        assert label == expected
        assert saved_score == score
        decoded = json.loads(raw)
        assert decoded["predictions"][0]["label"] == "Speaking"
        assert decoded["decision"]["label"] == expected
        assert decoded["decision"]["uncertain"] == (expected == "Uncertain result")
    finally:
        connection.close()
