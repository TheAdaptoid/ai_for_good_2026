"""Prompted classification contracts for in-memory RGB frames, never weights."""

import gc
import json
import math
from dataclasses import FrozenInstanceError, asdict
from types import SimpleNamespace
import weakref

import numpy as np
import pytest
import torch

from activity_classification.classifier import XCLIPClassifier
from activity_classification.runtime import MODEL_ID, MODEL_REVISION


REQUIRED_FRAMES = 8
CLASS_FRAME_SHAPE = (32, 8, 12, 3)


@pytest.fixture
def fake_classifier():
    state = SimpleNamespace(
        events=[], texts=None, token_length=5, shape=(1, 8, 3, 12, 12),
        logit_values=[1.0, 3.0], logit_dtype=torch.float32,
        error=None, tensor_refs=[], calls=0,
    )

    class ImageProcessor:
        @staticmethod
        def preprocess(videos, *, return_tensors, input_data_format):
            state.events.append("preprocess")
            assert input_data_format == "channels_last"
            assert len(videos) == REQUIRED_FRAMES
            assert all(isinstance(video, np.ndarray) and video.dtype == np.uint8
                       for video in videos)
            assert return_tensors == "pt"
            return {"pixel_values": torch.zeros(state.shape)}

    class Processor:
        image_processor = ImageProcessor()

        def __call__(self, *args, **kwargs):
            pytest.fail("Use the explicit tokenizer/image_processor components, not the combined call")

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
            vision_config=SimpleNamespace(num_frames=REQUIRED_FRAMES, image_size=12),
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
            assert tuple(inputs["pixel_values"].shape) == state.shape
            assert inputs["pixel_values"].dtype == fake.dtype
            state.tensor_refs.extend(weakref.ref(tensor) for tensor in inputs.values())
            if state.error:
                raise state.error
            logits = torch.tensor([state.logit_values], dtype=state.logit_dtype)
            state.tensor_refs.append(weakref.ref(logits))
            return SimpleNamespace(logits_per_video=logits)

    fake = XCLIPClassifier.__new__(XCLIPClassifier)
    fake.device = torch.device("cpu")
    fake.dtype = torch.float32
    fake.model_revision = MODEL_REVISION
    fake.num_frames = REQUIRED_FRAMES
    fake.image_size = 12
    fake.processor = Processor()
    fake.model = Model()
    fake.state = state
    return fake


def test_frames_are_adapted_and_labels_remain_aligned(fake_classifier):
    frames = np.zeros(CLASS_FRAME_SHAPE, dtype=np.uint8)
    result = fake_classifier.classify(frames, ["Walking", "Dancing"])

    assert result.selected_frame_indices == (0, 4, 8, 13, 17, 22, 26, 31)
    assert [p.label for p in result.predictions] == ["Dancing", "Walking"]
    assert [p.logit for p in result.predictions] == [3.0, 1.0]
    assert sum(p.score for p in result.predictions) == pytest.approx(1.0)
    assert result.predictions[0].prompt == "A video of people dancing."
    assert result.score_type == "candidate_relative_softmax"


@pytest.mark.parametrize("frames", [
    np.empty((0, 8, 12, 3), dtype=np.uint8),
    np.zeros((32, 8, 12, 3), dtype=np.float32),
    np.zeros((32, 8, 12, 1), dtype=np.uint8),
])
def test_invalid_rgb_input_is_rejected(fake_classifier, frames):
    with pytest.raises(ValueError):
        fake_classifier.classify(frames, ["Walking", "Dancing"])
    assert fake_classifier.state.calls == 0


def test_sequence_frame_input_is_accepted(fake_classifier):
    frames = [np.full((8, 12, 3), index, np.uint8) for index in range(5)]

    result = fake_classifier.classify(frames, ["Walking", "Dancing"])

    assert result.input_frame_count == 5
    assert result.selected_frame_indices == (0, 0, 1, 1, 2, 2, 3, 4)
    assert result.predictions[0].score >= result.predictions[1].score


@pytest.mark.parametrize("mutation", [
    "different_height_third_frame",
    "different_width_last_frame",
    "greyscale_frame",
    "float_frame",
])
def test_inconsistent_sequence_dimensions_are_rejected_even_for_unselected_frames(
    fake_classifier, mutation,
):
    frames = [np.zeros((8, 12, 3), np.uint8) for _ in range(16)]
    # 8 selected indices are (0, 2, 4, 6, 8, 10, 12, 15); odd slots stay unselected.
    if mutation == "different_height_third_frame":
        frames[3] = np.zeros((9, 12, 3), np.uint8)
    elif mutation == "different_width_last_frame":
        frames[13] = np.zeros((8, 11, 3), np.uint8)
    elif mutation == "greyscale_frame":
        frames[5] = np.zeros((8, 12), np.uint8)
    elif mutation == "float_frame":
        frames[9] = np.zeros((8, 12, 3), np.float32)

    with pytest.raises(ValueError):
        fake_classifier.classify(frames, ["Walking", "Dancing"])
    assert fake_classifier.state.calls == 0


@pytest.mark.parametrize("shape", [(0, 8, 12, 3), (8, 0, 12, 3), (8, 12, 0, 3)])
def test_zero_area_or_empty_array_input_is_rejected(fake_classifier, shape):
    with pytest.raises(ValueError):
        fake_classifier.classify(np.zeros(shape, np.uint8), ["Walking", "Dancing"])
    assert fake_classifier.state.calls == 0


def test_array_input_rejects_wrong_rank_and_missing_channels(fake_classifier):
    with pytest.raises(ValueError):
        fake_classifier.classify(np.zeros((8, 12), np.uint8), ["Walking", "Dancing"])
    with pytest.raises(ValueError):
        fake_classifier.classify(np.zeros((8, 8, 12, 4), np.uint8), ["Walking", "Dancing"])
    with pytest.raises(TypeError):
        fake_classifier.classify("not frames", ["Walking", "Dancing"])
    assert fake_classifier.state.calls == 0


def test_shorter_input_repeats_boundary_references(fake_classifier):
    frames = np.zeros((3, 8, 12, 3), dtype=np.uint8)

    result = fake_classifier.classify(frames, ["Walking", "Dancing"])

    assert result.selected_frame_indices == (0, 0, 0, 0, 1, 1, 1, 2)
    assert result.input_frame_count == 3


def test_native_frame_count_is_unchanged(fake_classifier):
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    result = fake_classifier.classify(frames, ["Running", "Jogging"])

    assert result.selected_frame_indices == tuple(range(8))
    assert result.input_frame_count == 8


def test_original_labels_keep_case_and_default_prompts_lowercase(fake_classifier):
    state = fake_classifier.state
    state.logit_values = [3.0, 1.0]
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    result = fake_classifier.classify(frames, ["  Running  ", "WALKING"])

    assert [p.label for p in result.predictions] == ["Running", "WALKING"]
    assert [p.prompt for p in result.predictions] == [
        "A video of people running.", "A video of people walking.",
    ]


def test_descriptions_reach_tokenizer_and_predictions(fake_classifier):
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)
    descriptions = {"Walking": "Someone strolling.", "Dancing": "A dancer moving."}

    result = fake_classifier.classify(frames, ["Walking", "Dancing"], descriptions=descriptions)

    assert fake_classifier.state.texts == ["Someone strolling.", "A dancer moving."]
    assert [p.prompt for p in result.predictions] == ["A dancer moving.", "Someone strolling."]


def test_identity_template_keeps_original_case(fake_classifier):
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    result = fake_classifier.classify(frames, ["Running"], prompt_template="{activity}")

    assert [p.prompt for p in result.predictions] == ["Running"]


@pytest.mark.parametrize("activities", [
    [], ("Walking",), ["Walking", " walking "], [""], [1], [None], ["!!!"],
    ["跑步"], ["a-b", "a b"],
])
def test_invalid_candidate_lists_are_rejected(fake_classifier, activities):
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    with pytest.raises((TypeError, ValueError)):
        fake_classifier.classify(frames, activities)
    assert fake_classifier.state.calls == 0


@pytest.mark.parametrize("template", [
    "{", "{unknown}", "{}", "{activity.name}", "{activity[0]}",
    "{activity!r}", "{activity:>80}", "   ",
])
def test_invalid_prompt_templates_are_rejected(fake_classifier, template):
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    with pytest.raises(ValueError):
        fake_classifier.classify(frames, ["Walking"], prompt_template=template)
    assert fake_classifier.state.calls == 0


@pytest.mark.parametrize("descriptions", [
    {}, {"Walking": "walks"},
    {"Walking": "walks", "Dancing": "dances", "Extra": "extra"},
    {"walking": "walks", "Dancing": "dances"},
    {"Walking": " ", "Dancing": "dances"},
    {"Walking": 7, "Dancing": "dances"}, ["walks", "dances"],
])
def test_descriptions_must_exactly_cover_labels_with_nonempty_text(fake_classifier, descriptions):
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    with pytest.raises((TypeError, ValueError)):
        fake_classifier.classify(frames, ["Walking", "Dancing"], descriptions=descriptions)
    assert fake_classifier.state.calls == 0


def test_stable_ties_keep_candidate_order(fake_classifier):
    state = fake_classifier.state
    state.logit_values = [2.0, 2.0]
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    result = fake_classifier.classify(frames, ["Walking", "Dancing"])

    assert [p.label for p in result.predictions] == ["Walking", "Dancing"]
    assert [p.score for p in result.predictions] == pytest.approx([0.5, 0.5])


@pytest.mark.parametrize("length,accepted", [(77, True), (78, False)])
def test_token_limit_never_silently_truncates(fake_classifier, length, accepted):
    state = fake_classifier.state
    state.token_length = length
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    if accepted:
        fake_classifier.classify(frames, ["Walking", "Dancing"])
        assert state.calls == 1
    else:
        with pytest.raises(ValueError, match="(?i)(77|token)"):
            fake_classifier.classify(frames, ["Walking", "Dancing"])
        assert state.calls == 0


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_logits_are_rejected_before_softmax(fake_classifier, monkeypatch, value):
    state = fake_classifier.state
    state.logit_values[0] = value
    monkeypatch.setattr(torch, "softmax", lambda *a, **k: pytest.fail("Nonfinite logits reached softmax"))
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    with pytest.raises(ValueError, match="(?i)finite"):
        fake_classifier.classify(frames, ["Walking", "Dancing"])


def test_nonfinite_softmax_scores_are_rejected(fake_classifier, monkeypatch):
    monkeypatch.setattr(torch, "softmax", lambda *a, **k: torch.tensor([math.nan, math.nan]))
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    with pytest.raises(ValueError, match="(?i)finite"):
        fake_classifier.classify(frames, ["Walking", "Dancing"])


def test_half_precision_outputs_are_softmaxed_in_float32(fake_classifier, monkeypatch):
    state = fake_classifier.state
    state.logit_dtype = torch.float16
    softmax = torch.softmax

    def checked_softmax(tensor, *args, **kwargs):
        assert tensor.dtype == torch.float32
        return softmax(tensor, *args, **kwargs)

    monkeypatch.setattr(torch, "softmax", checked_softmax)
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    result = fake_classifier.classify(frames, ["Walking", "Dancing"])

    assert [p.score for p in result.predictions] == pytest.approx([0.8807970779778823, 0.11920292202211755])
    json.dumps({p.label: p.score for p in result.predictions}, allow_nan=False)


def test_classification_returns_complete_frozen_result(fake_classifier):
    fake, state = fake_classifier, fake_classifier.state
    frames = np.zeros(CLASS_FRAME_SHAPE, dtype=np.uint8)

    result = fake.classify(frames, ["Walking", "Dancing"])

    assert result.model == MODEL_ID
    assert result.model_revision == MODEL_REVISION
    assert result.device == "cpu"
    assert result.dtype == "torch.float32"
    assert result.input_frame_count == 32
    assert result.num_frames == 8
    assert isinstance(result.selected_frame_indices, tuple)
    assert all(type(index) is int for index in result.selected_frame_indices)
    assert all(type(value) is float for value in (
        result.preprocessing_time_seconds, result.inference_time_seconds,
        result.total_time_seconds,
    ))
    assert all(0 <= value < 500 for value in (
        result.preprocessing_time_seconds, result.inference_time_seconds,
        result.total_time_seconds,
    ))
    assert result.total_time_seconds >= (
        result.preprocessing_time_seconds + result.inference_time_seconds
    )
    assert result.peak_gpu_memory_allocated_mib is None
    assert result.peak_gpu_memory_reserved_mib is None
    prediction = result.predictions[0]
    assert isinstance(prediction.label, str) and isinstance(prediction.prompt, str)
    assert type(prediction.logit) is float and type(prediction.score) is float
    json.dumps(asdict(result), allow_nan=False)
    with pytest.raises(FrozenInstanceError):
        result.device = "changed"
    with pytest.raises(FrozenInstanceError):
        result.predictions[0].label = "changed"
    assert state.events == ["tokenize", "preprocess", "forward"]


def test_tensors_are_released_after_classification(fake_classifier):
    fake, state = fake_classifier, fake_classifier.state
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    fake.classify(frames, ["Walking", "Dancing"])

    gc.collect()
    assert state.tensor_refs
    assert all(ref() is None for ref in state.tensor_refs)


def mock_cuda_gpu(monkeypatch, fake, state):
    fake.device = torch.device("cuda:0")
    fake.dtype = torch.float16
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
    monkeypatch.setattr(torch.cuda, "max_memory_allocated",
                        lambda device: state.events.append("allocated") or 123 * 2**20)
    monkeypatch.setattr(torch.cuda, "max_memory_reserved",
                        lambda device: state.events.append("reserved") or 256 * 2**20)


def test_cuda_transfer_integer_dtype_and_memory_measurements(fake_classifier, monkeypatch):
    fake, state = fake_classifier, fake_classifier.state
    mock_cuda_gpu(monkeypatch, fake, state)
    frames = np.zeros((16, 8, 12, 3), dtype=np.uint8)

    result = fake.classify(frames, ["Walking", "Dancing"])

    assert state.events == [
        "sync", "reset", "tokenize", "preprocess",
        "transfer", "transfer", "transfer", "forward", "sync",
        "allocated", "reserved",
    ]
    assert result.device == "cuda:0"
    assert result.dtype == "torch.float16"
    assert result.input_frame_count == 16
    assert result.peak_gpu_memory_allocated_mib == 123.0
    assert result.peak_gpu_memory_reserved_mib == 256.0
    gc.collect()
    assert all(ref() is None for ref in state.tensor_refs)


@pytest.mark.parametrize("failure", ["oom", "other"])
def test_cuda_errors_release_tensors_and_never_retry_cpu(fake_classifier, monkeypatch, failure):
    fake, state = fake_classifier, fake_classifier.state
    mock_cuda_gpu(monkeypatch, fake, state)
    state.error = (torch.OutOfMemoryError("fake allocation failure") if failure == "oom"
                   else ValueError("fake forward failure"))
    frames = np.zeros((8, 8, 12, 3), dtype=np.uint8)

    with pytest.raises((RuntimeError, ValueError)) as caught:
        fake.classify(frames, ["Walking", "Dancing"])

    if failure == "oom":
        assert "device='cpu'" in str(caught.value)
        assert caught.value.__cause__ is state.error
    else:
        assert caught.value is state.error
    assert state.calls == 1
    assert fake.device == torch.device("cuda:0")
    gc.collect()
    assert all(ref() is None for ref in state.tensor_refs)


def test_real_image_processor_routes_selected_frames_without_weights(fake_classifier):
    from transformers import VideoMAEImageProcessor

    fake, state = fake_classifier, fake_classifier.state
    fake.image_size = 224
    fake.model.config.vision_config.image_size = 224
    state.shape = (1, 8, 3, 224, 224)
    fake.processor.image_processor = VideoMAEImageProcessor()
    frames = np.full(CLASS_FRAME_SHAPE, 255, dtype=np.uint8)

    result = fake.classify(frames, ["Walking", "Dancing"])

    assert result.num_frames == 8
    assert result.selected_frame_indices == (0, 4, 8, 13, 17, 22, 26, 31)
    assert [p.label for p in result.predictions] == ["Dancing", "Walking"]


def test_prepared_batch_stays_on_cpu_and_returns_every_row(fake_classifier):
    from transformers import VideoMAEImageProcessor, XCLIPConfig, XCLIPModel
    torch.manual_seed(42)
    fake = fake_classifier
    fake.model = XCLIPModel(XCLIPConfig(
        text_config={"vocab_size":64,"hidden_size":16,"intermediate_size":32,
                     "num_hidden_layers":1,"num_attention_heads":4,
                     "max_position_embeddings":16,"bos_token_id":1,"eos_token_id":3},
        vision_config={"hidden_size":16,"intermediate_size":32,"num_hidden_layers":1,
                       "num_attention_heads":4,"image_size":12,"patch_size":4,
                       "num_frames":8,"mit_hidden_size":16,"mit_intermediate_size":32,
                       "mit_num_hidden_layers":1,"mit_num_attention_heads":4},
        projection_dim=16,prompt_num_attention_heads=4,prompt_layers=1,
        attn_implementation="eager",
    )).eval()
    fake.processor.image_processor = VideoMAEImageProcessor(
        size={"shortest_edge":12},crop_size={"height":12,"width":12})
    fake.processor.tokenizer = lambda *a, **k: {
        "input_ids": torch.tensor([[1,2,3],[1,4,3]]),
        "attention_mask": torch.ones((2,3),dtype=torch.long),
    }
    clips = [np.zeros((8,12,12,3),np.uint8), np.full((8,12,12,3),220,np.uint8)]
    batch = fake.prepare_batch(clips,["Walking","Dancing"])
    assert batch.inputs["pixel_values"].shape == (2,8,3,12,12)
    assert all(t.device.type == "cpu" for t in batch.inputs.values())
    results = fake.classify_prepared_batch(batch)
    assert len(results) == 2
    for clip, result in zip(clips,results):
        single = fake.classify(clip,["Walking","Dancing"])
        actual = {p.label:p.logit for p in result.predictions}
        expected = {p.label:p.logit for p in single.predictions}
        assert actual == pytest.approx(expected,abs=1e-4)
        assert sum(p.score for p in result.predictions) == pytest.approx(1)
    assert len(fake.classify_batch(clips[:1],["Walking","Dancing"])) == 1
    with pytest.raises(ValueError):
        fake.prepare_batch([], ["Walking"])
