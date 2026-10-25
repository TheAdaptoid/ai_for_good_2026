"""Runtime contracts without downloading or transferring model weights."""

import importlib
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace

import huggingface_hub
from huggingface_hub.errors import LocalEntryNotFoundError
import pytest
import torch

from activity_classification.classifier import XCLIPClassifier
from activity_classification import runtime as runtime_module

BACKEND_ROOT = Path(__file__).resolve().parents[1]

RUNTIME_ENV_KEYS = (
    "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK", "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE", "WANDB_DISABLED", "WANDB_MODE", "COMET_MODE",
    "TOKENIZERS_PARALLELISM", "HF_HOME", "HF_HUB_CACHE",
)


def expected_runtime_env(cache_dir: Path, *, offline: bool) -> dict:
    cache_dir = Path(cache_dir)
    return {
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "HF_HUB_OFFLINE": "1" if offline else "0",
        "TRANSFORMERS_OFFLINE": "1" if offline else "0",
        "WANDB_DISABLED": "true",
        "WANDB_MODE": "disabled",
        "COMET_MODE": "DISABLED",
        "TOKENIZERS_PARALLELISM": "false",
        "HF_HOME": str(cache_dir.parent),
        "HF_HUB_CACHE": str(cache_dir),
    }


@pytest.fixture
def guard_runtime_env(monkeypatch):
    # Record the pre-existing values so production os.environ updates are reverted.
    for key in RUNTIME_ENV_KEYS:
        monkeypatch.setenv(key, "PRESERVE")


@pytest.fixture
def runtime(guard_runtime_env, monkeypatch, tmp_path):
    events = []
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")
    state = SimpleNamespace(
        num_frames=8, image_size=12, max_position_embeddings=77,
        processor_error=None, model_error=None, transfer_error=None,
        snapshot_error=None, events=events, snapshot=snapshot,
    )

    def resolve(**kwargs):
        events.append(("snapshot", kwargs))
        if state.snapshot_error:
            raise state.snapshot_error
        return str(snapshot)

    class FakeModel:
        def __init__(self):
            self.config = SimpleNamespace(
                vision_config=SimpleNamespace(
                    num_frames=state.num_frames, image_size=state.image_size,
                ),
                text_config=SimpleNamespace(
                    max_position_embeddings=state.max_position_embeddings,
                ),
            )
            self.training = True
            self.device = None

        def to(self, device):
            events.append(("to", device))
            if state.transfer_error:
                raise state.transfer_error
            self.device = device
            return self

        def eval(self):
            events.append(("eval",))
            self.training = False
            return self

    class ModelFactory:
        @staticmethod
        def from_pretrained(path, **kwargs):
            events.append(("model", path, kwargs))
            if state.model_error:
                raise state.model_error
            return FakeModel()

    class ProcessorFactory:
        @staticmethod
        def from_pretrained(path, **kwargs):
            events.append(("processor", path, kwargs))
            if state.processor_error:
                raise state.processor_error
            return SimpleNamespace(snapshot=path)

    transformers = ModuleType("transformers")
    transformers.XCLIPModel = ModelFactory  # type: ignore[attr-defined]
    transformers.XCLIPProcessor = ProcessorFactory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", resolve)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.cuda, "current_device", lambda: 0)
    monkeypatch.setattr(torch.cuda, "synchronize", lambda device: events.append(("sync", device)))
    return state


def test_configure_runtime_overrides_external_settings(guard_runtime_env, monkeypatch):
    runtime_module = importlib.import_module("activity_classification.runtime")
    for key in RUNTIME_ENV_KEYS:
        monkeypatch.setenv(key, "external-setting")

    runtime_module.configure_runtime(offline=True, cache_dir=runtime_module.DEFAULT_CACHE_DIR)

    assert {key: os.environ[key] for key in RUNTIME_ENV_KEYS} == expected_runtime_env(
        runtime_module.DEFAULT_CACHE_DIR, offline=True,
    )


def test_configure_runtime_online_mode_keeps_telemetry_off(guard_runtime_env, monkeypatch, tmp_path):
    runtime_module = importlib.import_module("activity_classification.runtime")
    for key in RUNTIME_ENV_KEYS:
        monkeypatch.setenv(key, "external-setting")
    cache_dir = tmp_path / "acquire-hub"

    runtime_module.configure_runtime(offline=False, cache_dir=cache_dir)

    assert {key: os.environ[key] for key in RUNTIME_ENV_KEYS} == expected_runtime_env(
        cache_dir, offline=False,
    )
    assert os.environ["HF_HUB_OFFLINE"] == "0"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "0"


def test_runtime_paths_are_backend_derived():
    assert runtime_module.BACKEND_DIR == BACKEND_ROOT
    assert runtime_module.HF_HOME == BACKEND_ROOT / ".cache" / "huggingface"
    assert runtime_module.DEFAULT_CACHE_DIR == runtime_module.HF_HOME / "hub"
    assert runtime_module.MODEL_ID == "microsoft/xclip-base-patch16-zero-shot"
    assert (runtime_module.MODEL_REVISION ==
            "6746d6a5202bf24300cd9bf36f457f174483d41b")
    assert (runtime_module.DEFAULT_PROMPT_TEMPLATE ==
            "A video of people {activity}.")


def test_explicit_fp32_loads_original_precision_on_cuda(runtime, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    classifier = XCLIPClassifier(device="cuda", precision="fp32")
    event = next(e for e in runtime.events if e[0] == "model")
    assert event[2]["dtype"] == torch.float32
    assert classifier.dtype == torch.float32


@pytest.mark.parametrize("precision", ["invalid", "fp16"])
def test_invalid_or_half_cpu_precision_is_rejected(runtime, precision):
    with pytest.raises(ValueError, match="precision|FP16"):
        XCLIPClassifier(device="cpu", precision=precision)


@pytest.mark.parametrize("device", ["cpu", "auto"])
def test_cpu_initialization_pins_local_safetensors_and_eval(runtime, device):
    classifier = XCLIPClassifier(device=device)

    assert classifier.device == torch.device("cpu")
    assert classifier.dtype == torch.float32
    assert classifier.num_frames == 8
    assert classifier.image_size == 12
    assert classifier.model_revision == runtime_module.MODEL_REVISION
    assert classifier.processor.snapshot == str(runtime.snapshot)
    assert classifier.model.device == classifier.device
    assert classifier.model.training is False
    assert isinstance(classifier.load_time_seconds, float)
    assert classifier.load_time_seconds > 0
    assert ("snapshot", {
        "repo_id": runtime_module.MODEL_ID,
        "revision": runtime_module.MODEL_REVISION,
        "cache_dir": runtime_module.DEFAULT_CACHE_DIR,
        "local_files_only": True,
    }) in runtime.events
    snapshot_index = runtime.events.index(
        next(event for event in runtime.events if event[0] == "snapshot"))
    processor_index = runtime.events.index(
        next(event for event in runtime.events if event[0] == "processor"))
    model_index = runtime.events.index(
        next(event for event in runtime.events if event[0] == "model"))
    assert snapshot_index < processor_index < model_index
    processor = runtime.events[processor_index]
    assert processor[1] == str(runtime.snapshot)
    assert processor[2] == {"local_files_only": True, "trust_remote_code": False}
    model = runtime.events[model_index]
    assert model[1] == str(runtime.snapshot)
    assert model[2] == {
        "local_files_only": True, "use_safetensors": True,
        "trust_remote_code": False, "dtype": torch.float32,
        "attn_implementation": "eager",
    }
    assert not any(event[0] == "sync" for event in runtime.events)


def test_explicit_cache_dir_is_passed_to_snapshot(runtime, tmp_path):
    hub = tmp_path / "custom-hub"

    classifier = XCLIPClassifier(cache_dir=hub)

    assert ("snapshot", {
        "repo_id": runtime_module.MODEL_ID,
        "revision": runtime_module.MODEL_REVISION,
        "cache_dir": hub,
        "local_files_only": True,
    }) in runtime.events


def test_direct_model_path_loads_without_hub_snapshot(runtime, tmp_path):
    direct = tmp_path / "direct"
    direct.mkdir()
    (direct / "tokenizer.json").write_text("{}", encoding="utf-8")

    classifier = XCLIPClassifier(model_path=direct)

    assert not any(event[0] == "snapshot" for event in runtime.events)
    assert classifier.processor.snapshot == str(direct)
    assert classifier.num_frames == 8
    assert classifier.model.training is False


def test_model_path_and_cache_dir_are_mutually_exclusive(runtime, tmp_path):
    with pytest.raises(ValueError, match="(?i)both|model_path|cache_dir"):
        XCLIPClassifier(model_path=tmp_path, cache_dir=tmp_path / "hub")


@pytest.mark.parametrize("model_path", ["https://example.com/model", "file:///tmp/model"])
def test_uri_schemes_are_rejected(runtime, model_path):
    with pytest.raises(ValueError, match="(?i)uri|local"):
        XCLIPClassifier(model_path=model_path)


def test_absent_model_path_is_rejected(runtime, tmp_path):
    with pytest.raises(ValueError, match="(?i)exist|directory"):
        XCLIPClassifier(model_path=tmp_path / "missing")


@pytest.mark.parametrize("device", ["auto", "cuda", "cuda:0"])
def test_cuda_uses_half_precision_and_times_completed_initialization(
    runtime, monkeypatch, device,
):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)

    classifier = XCLIPClassifier(device=device)

    assert classifier.device == torch.device("cuda", 0)
    assert classifier.dtype == torch.float16
    assert classifier.model.device == classifier.device
    assert classifier.model.training is False
    model_event = next(event for event in runtime.events if event[0] == "model")
    assert model_event[2]["dtype"] == torch.float16
    assert "torch_dtype" not in model_event[2]
    assert runtime.events[-3:] == [
        ("to", classifier.device), ("eval",), ("sync", classifier.device),
    ]
    assert classifier.load_time_seconds > 0


def test_explicit_cpu_overrides_available_cuda(runtime, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)

    classifier = XCLIPClassifier(device="cpu")

    assert classifier.device == torch.device("cpu")
    assert classifier.dtype == torch.float32
    assert not any(event[0] == "sync" for event in runtime.events)


def test_explicit_cuda_unavailable_is_actionable_before_loading(runtime):
    with pytest.raises(RuntimeError, match="(?i)cuda.*cpu"):
        XCLIPClassifier(device="cuda")

    assert not any(event[0] == "snapshot" for event in runtime.events)


def test_cuda_transfer_failure_does_not_retry_on_cpu(runtime, monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    runtime.transfer_error = torch.OutOfMemoryError("test GPU allocation failure")

    with pytest.raises(torch.OutOfMemoryError, match="test GPU allocation failure"):
        XCLIPClassifier()

    to_events = [event[1] for event in runtime.events if event[0] == "to"]
    assert len(to_events) == 1
    assert to_events[0].type == "cuda"


@pytest.mark.parametrize("declared", [0, -2, True, "8", None, 8.5])
def test_checkpoint_frame_count_must_be_a_positive_integer(runtime, declared):
    runtime.num_frames = declared

    with pytest.raises(RuntimeError, match="(?i)num_frames|frame"):
        XCLIPClassifier(device="cpu")


@pytest.mark.parametrize("declared", [0, -1])
def test_checkpoint_image_size_must_be_a_positive_integer(runtime, declared):
    runtime.image_size = declared

    with pytest.raises(RuntimeError, match="(?i)image_size"):
        XCLIPClassifier(device="cpu")


@pytest.mark.parametrize("failure", ["snapshot_error", "processor_error", "model_error"])
def test_missing_or_incomplete_cache_names_command_cache_and_revision(runtime, failure):
    error = (LocalEntryNotFoundError("missing cached revision") if failure == "snapshot_error"
             else OSError("missing local asset"))
    setattr(runtime, failure, error)

    with pytest.raises(
        RuntimeError, match=r"uv run --locked python -m activity_classification\.download_model",
    ) as caught:
        XCLIPClassifier()

    assert caught.value.__cause__ is error
    message = str(caught.value)
    assert runtime_module.MODEL_REVISION in message
    assert str(runtime_module.DEFAULT_CACHE_DIR) in message


@pytest.mark.parametrize("present_asset", [None, "vocab.json", "merges.txt"])
def test_partial_tokenizer_snapshot_has_actionable_error(runtime, present_asset):
    (runtime.snapshot / "tokenizer.json").unlink()
    if present_asset:
        (runtime.snapshot / present_asset).write_text("{}", encoding="utf-8")
    missing = "merges.txt" if present_asset == "vocab.json" else "vocab.json"

    with pytest.raises(
        RuntimeError, match=r"uv run --locked python -m activity_classification\.download_model",
    ) as caught:
        XCLIPClassifier(device="cpu")

    assert isinstance(caught.value.__cause__, FileNotFoundError)
    assert missing in str(caught.value.__cause__)


def test_slow_tokenizer_asset_pair_is_accepted(runtime):
    (runtime.snapshot / "tokenizer.json").unlink()
    (runtime.snapshot / "vocab.json").write_text("{}", encoding="utf-8")
    (runtime.snapshot / "merges.txt").write_text("#version: 0.2\n", encoding="utf-8")

    classifier = XCLIPClassifier(device="cpu")

    assert classifier.processor.snapshot == str(runtime.snapshot)
    assert classifier.model.training is False


@pytest.mark.parametrize("failure", ["processor_error", "model_error"])
def test_unrelated_loader_programming_error_is_not_disguised_as_cache_failure(
    runtime, failure,
):
    error = TypeError("unrelated loader programming error")
    setattr(runtime, failure, error)

    with pytest.raises(TypeError) as caught:
        XCLIPClassifier(device="cpu")

    assert caught.value is error


def test_no_recognizer_factory_or_global_cache_exists():
    import activity_classification.classifier as classifier_module

    for forbidden in ("get_recognizer", "get_classifier", "cache_clear", "cache"):
        assert not hasattr(classifier_module, forbidden)


DOWNLOAD_SCRIPT = BACKEND_ROOT / "activity_classification" / "download_model.py"


def test_downloader_import_has_no_side_effects(guard_runtime_env, monkeypatch):
    assert DOWNLOAD_SCRIPT.is_file(), "Explicit download entry point is missing"
    before = dict(os.environ)

    def forbidden(**kwargs):
        pytest.fail("Import must not download")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", forbidden)
    namespace = runpy.run_path(str(DOWNLOAD_SCRIPT))

    assert callable(namespace["main"])
    assert dict(os.environ) == before


def test_explicit_download_enables_online_only_for_pinned_assets(
    guard_runtime_env, monkeypatch, capsys, tmp_path,
):
    assert DOWNLOAD_SCRIPT.is_file(), "Explicit download entry point is missing"
    for key in RUNTIME_ENV_KEYS:
        monkeypatch.setenv(key, "external-setting")
    monkeypatch.setattr(
        sys, "argv", ["download_model.py", "--cache-dir", str(tmp_path / "arg-hub")],
    )
    calls = []

    def download(**kwargs):
        assert {key: os.environ[key] for key in RUNTIME_ENV_KEYS} == expected_runtime_env(
            tmp_path / "arg-hub", offline=False,
        )
        calls.append(kwargs)
        return "/fake/pinned-snapshot"

    monkeypatch.setattr(huggingface_hub, "snapshot_download", download)
    runpy.run_path(str(DOWNLOAD_SCRIPT), run_name="__main__")

    assert calls == [{
        "repo_id": runtime_module.MODEL_ID,
        "revision": runtime_module.MODEL_REVISION,
        "cache_dir": tmp_path / "arg-hub",
        "allow_patterns": ["*.json", "merges.txt", "model.safetensors"],
    }]
    output = capsys.readouterr().out
    assert runtime_module.MODEL_REVISION in output
    assert "/fake/pinned-snapshot" in output


def test_explicit_download_defaults_to_backend_cache(
    guard_runtime_env, monkeypatch, capsys,
):
    monkeypatch.setattr(sys, "argv", ["download_model.py"])
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        return "/fake/pinned-snapshot"

    monkeypatch.setattr(huggingface_hub, "snapshot_download", download)
    runpy.run_path(str(DOWNLOAD_SCRIPT), run_name="__main__")

    assert calls[0]["cache_dir"] == runtime_module.DEFAULT_CACHE_DIR
    assert calls[0]["repo_id"] == runtime_module.MODEL_ID
    assert calls[0]["revision"] == runtime_module.MODEL_REVISION
    assert calls[0]["allow_patterns"] == ["*.json", "merges.txt", "model.safetensors"]
    assert os.environ["HF_HUB_OFFLINE"] == "0"


ISOLATION_SCRIPT = r"""
import builtins
import os
import socket
import sys
from pathlib import Path

FORBIDDEN_PACKAGE_ROOTS = {
    "torch", "transformers", "huggingface_hub", "cv2", "av",
    "activity_recognition", "notebooks",
}
real_import = builtins.__import__


def guarded_import(name, *args, **kwargs):
    root = name.split(".")[0]
    if root in FORBIDDEN_PACKAGE_ROOTS:
        raise AssertionError(f"Package import must be lazy and backend-local: {name}")
    return real_import(name, *args, **kwargs)


builtins.__import__ = guarded_import

import activity_classification

assert "torch" not in sys.modules
assert "transformers" not in sys.modules
assert "huggingface_hub" not in sys.modules
assert "cv2" not in sys.modules
assert "activity_recognition" not in sys.modules
assert list(activity_classification.__all__) == [
    "ActivityPrediction", "ClassificationResult", "RGBFrames", "XCLIPClassifier",
]
assert os.environ.get("HF_HUB_OFFLINE") != "1"
assert os.environ.get("TRANSFORMERS_OFFLINE") != "1"

from activity_classification import runtime as runtime_module

backend_dir = Path(activity_classification.__file__).resolve().parents[1]
assert backend_dir.is_dir()
assert not backend_dir.samefile(os.getcwd())
assert runtime_module.BACKEND_DIR == backend_dir
assert runtime_module.HF_HOME == backend_dir / ".cache" / "huggingface"
assert runtime_module.DEFAULT_CACHE_DIR == runtime_module.HF_HOME / "hub"
sibling = backend_dir / "notebooks"
assert sibling.is_dir(), "poison sibling must exist for this scenario"
assert runtime_module.DEFAULT_CACHE_DIR not in sibling.glob("**/*")
assert not sibling.is_relative_to(runtime_module.DEFAULT_CACHE_DIR.parent), \
    "backend defaults must not derive from the sibling notebook cache"

import numpy as np

builtins.__import__ = real_import


def block_network(*args, **kwargs):
    raise AssertionError("network connection attempted")


socket.socket.connect = block_network
socket.create_connection = block_network
socket.getaddrinfo = block_network

import torch

from activity_classification.classifier import XCLIPClassifier
from activity_classification.runtime import MODEL_REVISION

state = {"calls": 0}


class ImageProcessor:
    @staticmethod
    def preprocess(videos, *, return_tensors, input_data_format):
        assert input_data_format == "channels_last"
        assert len(videos) == 8
        return {"pixel_values": torch.zeros((1, 8, 3, 12, 12))}


class Processor:
    image_processor = ImageProcessor()

    def tokenizer(self, texts, **kwargs):
        assert kwargs["padding"] is True and kwargs["truncation"] is False
        assert kwargs["return_tensors"] == "pt"
        assert kwargs["return_token_type_ids"] is False
        return {
            "input_ids": torch.full((len(texts), 5), 42, dtype=torch.int64),
            "attention_mask": torch.ones((len(texts), 5), dtype=torch.int64),
        }


class Model:
    config = __import__("types").SimpleNamespace(
        vision_config=__import__("types").SimpleNamespace(num_frames=8, image_size=12),
        text_config=__import__("types").SimpleNamespace(max_position_embeddings=77),
    )

    def __call__(self, **inputs):
        state["calls"] += 1
        assert torch.is_inference_mode_enabled()
        logits = torch.tensor([[1.0, 3.0]], dtype=torch.float32)
        return __import__("types").SimpleNamespace(logits_per_video=logits)


fake = XCLIPClassifier.__new__(XCLIPClassifier)
fake.device = torch.device("cpu")
fake.dtype = torch.float32
fake.model_revision = MODEL_REVISION
fake.num_frames = 8
fake.image_size = 12
fake.processor = Processor()
fake.model = Model()
frames = np.zeros((16, 8, 12, 3), dtype=np.uint8)
result = fake.classify(frames, ["Walking", "Dancing"])
assert result.selected_frame_indices == (0, 2, 4, 6, 8, 10, 12, 15)
assert [p.label for p in result.predictions] == ["Dancing", "Walking"]
assert [p.logit for p in result.predictions] == [3.0, 1.0]
assert abs(sum(p.score for p in result.predictions) - 1.0) < 1e-6
assert result.num_frames == 8
assert result.input_frame_count == 16
assert result.device == "cpu"
assert result.peak_gpu_memory_allocated_mib is None
assert result.peak_gpu_memory_reserved_mib is None
assert state["calls"] == 1
print("ISOLATION_OK")
"""


def test_isolated_backend_subprocess_defaults_and_fake_classification():
    import shutil
    import tempfile

    isolation_dir = Path(tempfile.mkdtemp(prefix="xclip-iso-", dir="/tmp/opencode"))
    try:
        copy_dir = isolation_dir / "backend-copy"
        copy_dir.mkdir()
        shutil.copytree(
            BACKEND_ROOT / "activity_classification", copy_dir / "activity_classification",
        )
        sibling = copy_dir / "notebooks" / ".cache" / "huggingface"
        sibling.mkdir(parents=True)
        (copy_dir / "notebooks" / "activity_recognition.py").write_text(
            "raise AssertionError('sibling import was attempted')\n", encoding="utf-8",
        )
        poisoned = dict(os.environ)
        poisoned.update({
            "HF_HOME": str(sibling),
            "HF_HUB_CACHE": str(sibling / "hub"),
            "HUGGINGFACE_HUB_CACHE": str(sibling / "hub"),
            "PYTHONPATH": str(copy_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        result = subprocess.run(
            [sys.executable, "-c", ISOLATION_SCRIPT],
            cwd=isolation_dir, env=poisoned, capture_output=True, text=True, timeout=600,
        )
        assert "ISOLATION_OK" in result.stdout, (
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    finally:
        shutil.rmtree(isolation_dir, ignore_errors=True)
