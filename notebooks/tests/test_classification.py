"""Prompted classification contracts using real CPU tensors, never model weights."""

from dataclasses import FrozenInstanceError
import gc
import json
import math
from types import SimpleNamespace
import weakref

import numpy as np
import pytest
import torch

import activity_recognition as ar


def test_candidates_normalize_keys_preserve_labels_and_are_frozen():
    candidates = ar.prepare_candidates(["  Playing Guitar  ", "RUNNING!"])

    assert [(c.key, c.label, c.prompt) for c in candidates] == [
        ("playing_guitar", "Playing Guitar", "A video of people playing guitar."),
        ("running", "RUNNING!", "A video of people running!."),
    ]
    with pytest.raises(FrozenInstanceError):
        candidates[0].key = "changed"


def test_prompt_wording_does_not_change_keys_or_original_case():
    labels = ["Playing Guitar", "Running"]
    identity = ar.prepare_candidates(labels, prompt_template="{activity}")
    described = ar.prepare_candidates(labels, descriptions={
        "Playing Guitar": " A person strums a guitar. ",
        "Running": "An athlete runs along a track.",
    })

    assert [c.key for c in identity] == [c.key for c in described] == ["playing_guitar", "running"]
    assert [c.prompt for c in identity] == labels
    assert described[0].prompt == "A person strums a guitar."


@pytest.mark.parametrize("activities", [
    [], "running", ("running",), [""], ["  "], [1], [None],
    ["Running", " running "], ["!!!"], ["跑步"], ["a-b", "a b"],
])
def test_invalid_candidate_labels_are_rejected(activities):
    with pytest.raises((TypeError, ValueError)):
        ar.prepare_candidates(activities)


@pytest.mark.parametrize("template", [
    "{", "{unknown}", "{}", "{activity.name}", "{activity[0]}",
    "{activity!r}", "{activity:>80}", "   ", None,
])
def test_bad_templates_are_rejected(template):
    with pytest.raises((TypeError, ValueError)):
        ar.prepare_candidates(["Running"], prompt_template=template)


@pytest.mark.parametrize("descriptions", [
    {}, {"Running": "runs"},
    {"Running": "runs", "Walking": "walks", "Extra": "extra"},
    {"running": "runs", "Walking": "walks"},
    {"Running": " ", "Walking": "walks"},
    {"Running": 7, "Walking": "walks"}, ["runs", "walks"],
])
def test_descriptions_must_exactly_cover_labels_with_nonempty_text(descriptions):
    with pytest.raises((TypeError, ValueError)):
        ar.prepare_candidates(["Running", "Walking"], descriptions=descriptions)


@pytest.fixture
def classification(monkeypatch):
    state = SimpleNamespace(
        events=[], token_length=5, shape=(1, 32, 3, 224, 224),
        logit_values=[2.0, 1.0], logit_dtype=torch.float32,
        error=None, tensor_refs=[], calls=0,
    )

    class ImageProcessor:
        def preprocess(self, *, videos, return_tensors):
            state.events.append("images")
            assert len(videos) == 32
            assert videos[0].dtype == np.uint8
            assert videos[0][0, 0, 0] > 240  # Genuine sampled RGB, not BGR.
            assert return_tensors == "pt"
            return {"pixel_values": torch.zeros(state.shape)}

    class Processor:
        image_processor = ImageProcessor()

        def __call__(self, *args, **kwargs):
            pytest.fail("Use the explicit tokenizer/image_processor compatibility route")

        def tokenizer(self, texts, **kwargs):
            state.events.append("tokenize")
            state.texts = texts
            assert kwargs == {
                "padding": True, "truncation": False, "return_tensors": "pt",
                "return_token_type_ids": False,
            }
            return {
                "input_ids": torch.full((len(texts), state.token_length), 42, dtype=torch.int64),
                "attention_mask": torch.ones((len(texts), state.token_length), dtype=torch.int64),
            }

    class Model:
        config = SimpleNamespace(
            vision_config=SimpleNamespace(num_frames=32),
            text_config=SimpleNamespace(max_position_embeddings=77),
        )

        def __call__(self, **inputs):
            state.events.append("forward")
            state.calls += 1
            assert not torch.is_grad_enabled()
            assert torch.is_inference_mode_enabled()
            assert set(inputs) == {"input_ids", "attention_mask", "pixel_values"}
            assert inputs["input_ids"].dtype == torch.int64
            assert inputs["attention_mask"].dtype == torch.int64
            assert inputs["input_ids"][0, 0].item() == 42
            assert inputs["pixel_values"].dtype == recognizer.dtype
            state.tensor_refs.extend(weakref.ref(tensor) for tensor in inputs.values())
            if state.error:
                raise state.error
            logits = torch.tensor([state.logit_values], dtype=state.logit_dtype)
            state.tensor_refs.append(weakref.ref(logits))
            return SimpleNamespace(logits_per_video=logits)

    recognizer = ar.XCLIPRecognizer.__new__(ar.XCLIPRecognizer)
    recognizer.device = torch.device("cpu")
    recognizer.dtype = torch.float32
    recognizer.model_revision = ar.MODEL_REVISION
    recognizer.load_time_seconds = 500.0
    recognizer.processor = Processor()
    recognizer.model = Model()
    return recognizer, state


def test_classification_returns_complete_finite_relative_scores(classification, make_video):
    recognizer, state = classification
    path = make_video(frames=3)

    result = recognizer.classify(str(path), ["Playing Guitar", "Running"])

    assert set(result) == {
        "video_id", "clip_start", "clip_end", "model", "model_revision", "activity",
        "scores", "logits", "labels", "prompts", "score_type", "num_frames",
        "unique_sampled_frames", "sampled_frame_indices", "sampling_method", "device",
        "dtype", "preprocessing_time_seconds", "inference_time_seconds", "total_time_seconds",
        "peak_gpu_memory_allocated_mib", "peak_gpu_memory_reserved_mib",
    }
    assert result["video_id"] == path.stem
    assert result["clip_start"] == 0.0
    assert result["clip_end"] == pytest.approx(0.1)
    assert result["model"] == "microsoft/xclip-base-patch16-zero-shot"
    assert result["model_revision"] == "6746d6a5202bf24300cd9bf36f457f174483d41b"
    assert result["activity"] == "playing_guitar"
    assert result["scores"] == pytest.approx({"playing_guitar": 0.7310585786, "running": 0.2689414214})
    assert sum(result["scores"].values()) == pytest.approx(1.0)
    assert result["logits"] == {"playing_guitar": 2.0, "running": 1.0}
    assert result["labels"] == {"playing_guitar": "Playing Guitar", "running": "Running"}
    assert result["prompts"] == {
        "playing_guitar": "A video of people playing guitar.", "running": "A video of people running.",
    }
    assert result["score_type"] == "candidate_relative_softmax"
    assert result["num_frames"] == 32
    assert result["unique_sampled_frames"] == 3
    assert result["sampled_frame_indices"] == [0] * 16 + [1] * 15 + [2]
    assert all(type(index) is int for index in result["sampled_frame_indices"])
    assert result["sampling_method"] == "uniform_frame_indices"
    assert result["device"] == "cpu"
    assert result["dtype"] == "torch.float32"
    assert result["peak_gpu_memory_allocated_mib"] is None
    assert result["peak_gpu_memory_reserved_mib"] is None
    for key in ("preprocessing_time_seconds", "inference_time_seconds", "total_time_seconds"):
        assert type(result[key]) is float
        assert 0 <= result[key] < 500
    assert result["total_time_seconds"] >= result["preprocessing_time_seconds"] + result["inference_time_seconds"]
    assert str(path) not in json.dumps(result, allow_nan=False)
    assert state.events == ["tokenize", "images", "forward"]
    assert all(ref() is None for ref in state.tensor_refs)


def test_wrapper_reuses_cached_model_and_excludes_load_time(classification, make_video, monkeypatch):
    recognizer, state = classification
    ar.get_recognizer.cache_clear()
    constructions = []

    def initialize(device):
        constructions.append(device)
        state.events.append("load")
        return recognizer

    monkeypatch.setattr(ar, "XCLIPRecognizer", initialize)
    monkeypatch.setattr(ar, "perf_counter", lambda: state.events.append("clock") or float(len(state.events)))
    path = str(make_video())
    try:
        first = ar.classify_activity(path, ["Running", "Walking"], video_id="custom", device="cpu")
        second = ar.classify_activity(path, ["Running", "Walking"], prompt_template="{activity}", device="cpu")
    finally:
        ar.get_recognizer.cache_clear()

    assert constructions == ["cpu"]
    assert state.calls == 2
    assert state.events[:2] == ["load", "clock"]
    assert first["video_id"] == "custom"
    assert list(first["scores"]) == list(second["scores"]) == ["running", "walking"]
    assert second["prompts"] == {"running": "Running", "walking": "Walking"}


@pytest.mark.parametrize("video_id", ["", "  ", 1, [], "bad\ud800"])
def test_invalid_video_id_is_rejected_before_inference(classification, make_video, video_id):
    recognizer, state = classification
    with pytest.raises((TypeError, ValueError)):
        recognizer.classify(str(make_video()), ["Running"], video_id=video_id)
    assert state.calls == 0


def test_descriptions_reach_tokenizer_and_result(classification, make_video):
    recognizer, state = classification
    descriptions = {"Running": "A runner on a track.", "Walking": "Someone strolling."}
    result = recognizer.classify(str(make_video()), ["Running", "Walking"], descriptions=descriptions)
    assert state.texts == list(descriptions.values())
    assert result["prompts"] == {"running": descriptions["Running"], "walking": descriptions["Walking"]}


@pytest.mark.parametrize("length,accepted", [(77, True), (78, False)])
def test_token_limit_never_silently_truncates(classification, make_video, length, accepted):
    recognizer, state = classification
    state.token_length = length
    if accepted:
        recognizer.classify(str(make_video()), ["Running", "Walking"])
        assert state.calls == 1
    else:
        with pytest.raises(ValueError, match="(?i)(77|long|token)"):
            recognizer.classify(str(make_video()), ["Running", "Walking"])
        assert state.calls == 0


@pytest.mark.parametrize("shape", [(1, 8, 3, 224, 224), (32, 3, 224, 224), (1, 32, 3, 112, 112)])
def test_wrong_temporal_or_spatial_shape_is_rejected(classification, make_video, shape):
    recognizer, state = classification
    state.shape = shape
    with pytest.raises(ValueError, match="(?i)(shape|32)"):
        recognizer.classify(str(make_video()), ["Running", "Walking"])
    assert state.calls == 0


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_logits_are_rejected_before_softmax(classification, make_video, monkeypatch, value):
    recognizer, state = classification
    state.logit_values[0] = value
    monkeypatch.setattr(torch, "softmax", lambda *args, **kwargs: pytest.fail("Nonfinite logits reached softmax"))
    with pytest.raises(ValueError, match="(?i)finite"):
        recognizer.classify(str(make_video()), ["Running", "Walking"])


def test_half_precision_outputs_are_softmaxed_in_float32(classification, make_video, monkeypatch):
    recognizer, state = classification
    state.logit_dtype = torch.float16
    softmax = torch.softmax

    def checked_softmax(tensor, *args, **kwargs):
        assert tensor.dtype == torch.float32
        return softmax(tensor, *args, **kwargs)

    monkeypatch.setattr(torch, "softmax", checked_softmax)
    result = recognizer.classify(str(make_video()), ["Running", "Walking"])
    assert result["scores"]["running"] == pytest.approx(0.7310585786, abs=1e-7)
    json.dumps(result, allow_nan=False)


def mock_cuda(monkeypatch, recognizer, state):
    recognizer.device = torch.device("cuda:0")
    recognizer.dtype = torch.float16
    original_to = torch.Tensor.to

    def transfer(tensor, *args, **kwargs):
        assert not args
        assert kwargs["device"] == torch.device("cuda:0")
        if tensor.is_floating_point():
            assert kwargs["dtype"] == torch.float16
        else:
            assert "dtype" not in kwargs
        state.events.append("transfer")
        return original_to(tensor, **{**kwargs, "device": "cpu"})

    monkeypatch.setattr(torch.Tensor, "to", transfer)
    monkeypatch.setattr(torch.cuda, "synchronize", lambda device: state.events.append("sync"))
    monkeypatch.setattr(torch.cuda, "reset_peak_memory_stats", lambda device: state.events.append("reset"))
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda device: state.events.append("allocated") or 123 * 2**20)
    monkeypatch.setattr(torch.cuda, "max_memory_reserved", lambda device: state.events.append("reserved") or 256 * 2**20)
    monkeypatch.setattr(ar, "perf_counter", lambda: state.events.append("clock") or float(len(state.events)))


def test_cuda_measurements_bound_preprocessing_transfer_and_completed_forward(classification, make_video, monkeypatch):
    recognizer, state = classification
    mock_cuda(monkeypatch, recognizer, state)
    result = recognizer.classify(str(make_video()), ["Running", "Walking"])

    assert state.events == [
        "clock", "sync", "reset", "tokenize", "images", "clock",
        "transfer", "transfer", "transfer", "forward", "sync", "clock",
        "allocated", "reserved", "clock",
    ]
    assert result["preprocessing_time_seconds"] == 5.0
    assert result["inference_time_seconds"] == 6.0
    assert result["total_time_seconds"] == 14.0
    assert result["peak_gpu_memory_allocated_mib"] == 123.0
    assert result["peak_gpu_memory_reserved_mib"] == 256.0
    assert result["device"] == "cuda:0"
    assert result["dtype"] == "torch.float16"
    assert all(ref() is None for ref in state.tensor_refs)


@pytest.mark.parametrize("failure", ["oom", "other"])
def test_cuda_errors_release_inputs_and_never_retry_cpu(classification, make_video, monkeypatch, failure):
    recognizer, state = classification
    mock_cuda(monkeypatch, recognizer, state)
    state.error = torch.OutOfMemoryError("fake allocation failure") if failure == "oom" else ValueError("fake forward failure")
    with pytest.raises((RuntimeError, ValueError)) as caught:
        recognizer.classify(str(make_video()), ["Running", "Walking"])
    if failure == "oom":
        assert "device='cpu'" in str(caught.value)
        assert caught.value.__cause__ is state.error
    else:
        assert caught.value is state.error
    assert state.calls == 1
    assert recognizer.device == torch.device("cuda:0")
    gc.collect()
    assert all(ref() is None for ref in state.tensor_refs)


def test_real_local_image_preprocessing_routes_32_rgb_frames(classification, make_video):
    from transformers import VideoMAEImageProcessor

    recognizer, _ = classification
    recognizer.processor.image_processor = VideoMAEImageProcessor()
    result = recognizer.classify(str(make_video(frames=3)), ["Running", "Walking"])
    assert result["num_frames"] == 32
    assert result["activity"] == "running"
