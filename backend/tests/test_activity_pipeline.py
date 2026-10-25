import json
import sqlite3
import threading
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from activity_classification.classifier import XCLIPClassifier
from activity_classification.runtime import MODEL_REVISION


@pytest.fixture
def fake_forward(monkeypatch):
    from transformers import VideoMAEImageProcessor
    import activity_pipeline.runner as runner

    class Model:
        config = SimpleNamespace(text_config=SimpleNamespace(max_position_embeddings=77))
        def __call__(self, pixel_values, input_ids, **kwargs):
            assert torch.is_inference_mode_enabled()
            means = pixel_values.mean(dim=(1,2,3,4))
            weights = torch.arange(input_ids.shape[0], dtype=torch.float32)
            return SimpleNamespace(logits_per_video=means[:,None] * weights[None,:])

    def create(**kwargs):
        c = XCLIPClassifier.__new__(XCLIPClassifier)
        c.device, c.dtype = torch.device("cpu"), torch.float32
        c.num_frames, c.image_size = 32, 12
        c.model_revision, c.load_time_seconds = MODEL_REVISION, 0.0
        c.model = Model()
        c.processor = SimpleNamespace(
            image_processor=VideoMAEImageProcessor(size={"shortest_edge":12},crop_size={"height":12,"width":12}),
            tokenizer=lambda texts, **kwargs: {"input_ids":torch.ones((len(texts),4),dtype=torch.long)},
        )
        return c
    monkeypatch.setattr(runner, "XCLIPClassifier", create)
    return runner


def test_persistence_resume_advances_limit_and_does_not_change_identities(video, fake_forward):
    runner = fake_forward
    with sqlite3.connect(video.db_path) as c:
        before = {t:c.execute(f"SELECT * FROM {t}").fetchall()
                  for t in ("Video","Frame","Person","FaceDetection","Engagement")}
    first = runner.run_activity(video.db_path,sample_size=None,limit=2,device="cpu")
    assert (first.selected,first.written,first.failed)==(4,2,0)
    assert first.report["remaining_frames"]==2
    assert first.report["seconds_per_frame"] == pytest.approx(first.report["processing_wall_seconds"]/2)
    second = runner.run_activity(video.db_path,sample_size=None,limit=2,device="cpu")
    assert (second.skipped,second.written)==(2,2)
    done = runner.run_activity(video.db_path,sample_size=None,device="cpu")
    assert (done.skipped,done.written)==(4,0)
    assert done.report["seconds_per_frame"] is None
    assert done.report["inference_batches"]==0
    with sqlite3.connect(video.db_path) as c:
        for t, rows in before.items():
            assert c.execute(f"SELECT * FROM {t}").fetchall()==rows
        results=c.execute("SELECT frame_id,result_json,sampling_json FROM Activity").fetchall()
        assert len(results)==4
        for _, result, sampling in results:
            assert len(json.loads(sampling)["source_frame_indices"])==32
            assert len(json.loads(result)["predictions"])==11


def test_seeded_resume_retries_failed_member_only(video, fake_forward, monkeypatch):
    runner=fake_forward
    original=runner.IndexedTemporalSampler.sample
    def fail_one(self, **kwargs):
        if kwargs["reference_frame_number"]==24:
            raise ValueError("bad clip")
        return original(self,**kwargs)
    monkeypatch.setattr(runner.IndexedTemporalSampler,"sample",fail_one)
    first=runner.run_activity(video.db_path,sample_size=4,seed=42,device="cpu")
    assert (first.attempted,first.written,first.failed)==(4,3,1)
    assert first.report["timing_sample"]=="partial"
    monkeypatch.setattr(runner.IndexedTemporalSampler,"sample",original)
    second=runner.run_activity(video.db_path,sample_size=4,seed=42,device="cpu")
    assert (second.skipped,second.written,second.failed)==(3,1,0)
    assert first.report["selected_frame_ids"]==second.report["selected_frame_ids"]


def test_fatal_write_preserves_old_result_and_stops_worker(video, fake_forward, monkeypatch):
    runner=fake_forward
    runner.run_activity(video.db_path,sample_size=None,device="cpu")
    with sqlite3.connect(video.db_path) as c:
        before=c.execute("SELECT * FROM Activity ORDER BY frame_id").fetchall()
        c.execute("CREATE TRIGGER no_update BEFORE UPDATE ON Activity BEGIN SELECT RAISE(ABORT,'injected'); END")
    monkeypatch.setattr(runner,"ACTIVITIES",("Walking","Dancing"))
    with pytest.raises(sqlite3.IntegrityError,match="injected"):
        runner.run_activity(video.db_path,sample_size=None,batch_size=1,device="cpu")
    assert not any(t.name=="activity-preparation" for t in threading.enumerate())
    with sqlite3.connect(video.db_path) as c:
        assert c.execute("SELECT * FROM Activity ORDER BY frame_id").fetchall()==before


def test_dry_run_does_not_load_model_or_decode(video, fake_forward, monkeypatch):
    runner=fake_forward
    def forbidden(*args,**kwargs):
        pytest.fail("Dry-run must not load a model or decode a source")
    monkeypatch.setattr(runner,"XCLIPClassifier",forbidden)
    monkeypatch.setattr(runner,"IndexedTemporalSampler",forbidden)
    summary=runner.run_activity(video.db_path,sample_size=3,seed=42,dry_run=True)
    assert summary.selected==3 and summary.written==0
    assert len(summary.report["selected_frame_ids"])==3


def test_all_cached_resume_needs_no_model_assets(video, fake_forward, monkeypatch):
    runner=fake_forward
    runner.run_activity(video.db_path,sample_size=None,device="cpu")
    def forbidden(**kwargs):
        pytest.fail("Cached resume must not load model weights")
    monkeypatch.setattr(runner,"XCLIPClassifier",forbidden)
    done=runner.run_activity(video.db_path,sample_size=None,device="cpu")
    assert done.skipped==4 and done.written==0


def test_interruption_keeps_completed_result_and_partial_report(video, fake_forward, monkeypatch):
    runner=fake_forward
    original=runner.save_activity
    writes=[]
    def interrupt(*args,**kwargs):
        if writes:
            raise KeyboardInterrupt()
        original(*args,**kwargs)
        writes.append(True)
    monkeypatch.setattr(runner,"save_activity",interrupt)
    with pytest.raises(KeyboardInterrupt) as caught:
        runner.run_activity(video.db_path,sample_size=None,device="cpu")
    assert caught.value.report["written"]==1
    assert caught.value.report["timing_sample"]=="partial"
    assert caught.value.report["interrupted"] is True
    with sqlite3.connect(video.db_path) as c:
        assert c.execute("SELECT COUNT(*) FROM Activity").fetchone()[0]==1
    assert not any(t.name=="activity-preparation" for t in threading.enumerate())


def test_preparation_overlaps_inference_with_bounded_queue(video, fake_forward, monkeypatch):
    runner=fake_forward
    create=runner.XCLIPClassifier
    fourth_prepared=threading.Event()
    observed=[]
    def factory(**kwargs):
        classifier=create(**kwargs)
        prepare=classifier.prepare_batch
        original_model=classifier.model
        prepared_count=0
        class PausedModel:
            config=original_model.config
            calls=0
            def __call__(self,**inputs):
                self.calls+=1
                if self.calls==2:  # Warm-up is first; pause the first real forward.
                    assert fourth_prepared.wait(10), "Producer did not prepare ahead of inference"
                    observed.append(True)
                return original_model(**inputs)
        def preparing(*args,**kwargs):
            nonlocal prepared_count
            batch=prepare(*args,**kwargs)
            if threading.current_thread().name=="activity-preparation":
                prepared_count+=1
                if prepared_count==4:
                    fourth_prepared.set()
            return batch
        classifier.model=PausedModel()
        classifier.prepare_batch=preparing
        return classifier
    monkeypatch.setattr(runner,"XCLIPClassifier",factory)
    done=runner.run_activity(video.db_path,sample_size=None,batch_size=1,prefetch_batches=2,device="cpu")
    assert observed==[True]
    assert done.written==4
    assert done.report["batch_sizes"]==[1,1,1,1]


def test_expanded_prompts_and_cutoff_are_used_and_invalidate_resume(video, fake_forward, monkeypatch):
    runner = fake_forward
    from activity_pipeline.config import ACTIVITY_DESCRIPTIONS, MIN_ACTIVITY_SCORE, UNCERTAIN_LABEL
    assert {"Acting", "Speaking"}.issubset(runner.ACTIVITIES)
    assert len(runner.ACTIVITIES) == 11
    assert UNCERTAIN_LABEL not in runner.ACTIVITIES
    first = runner.run_activity(video.db_path, sample_size=None, device="cpu")
    assert first.report["configuration"]["decision_policy"]["min_score_exclusive"] == 0.65
    assert first.report["configuration"]["prompts"] == [ACTIVITY_DESCRIPTIONS[k] for k in runner.ACTIVITIES]
    with sqlite3.connect(video.db_path) as c:
        for raw, in c.execute("SELECT result_json FROM Activity"):
            predictions = json.loads(raw)["predictions"]
            assert len(predictions) == 11
            assert all(p["prompt"] == ACTIVITY_DESCRIPTIONS[p["label"]] for p in predictions)
    monkeypatch.setattr(runner, "MIN_ACTIVITY_SCORE", MIN_ACTIVITY_SCORE + 0.01)
    second = runner.run_activity(video.db_path, sample_size=None, device="cpu")
    assert second.skipped == 0 and second.written == 4
    revised = dict(ACTIVITY_DESCRIPTIONS)
    revised["Speaking"] += " The speaker gestures toward the group."
    monkeypatch.setattr(runner, "ACTIVITY_DESCRIPTIONS", revised)
    third = runner.run_activity(video.db_path, sample_size=None, device="cpu")
    assert third.skipped == 0 and third.written == 4
