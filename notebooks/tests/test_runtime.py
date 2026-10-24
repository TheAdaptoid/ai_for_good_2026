"""Runtime contracts without downloading or transferring real model weights."""

import importlib
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import huggingface_hub
from huggingface_hub.errors import LocalEntryNotFoundError
import pytest
import torch


PROJECT_DIR = Path(__file__).resolve().parents[1]
REVISION = "6746d6a5202bf24300cd9bf36f457f174483d41b"
OFFLINE_ENV = {
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "WANDB_DISABLED": "true",
    "WANDB_MODE": "disabled",
    "COMET_MODE": "DISABLED",
    "TOKENIZERS_PARALLELISM": "false",
    "HF_HOME": str(PROJECT_DIR / ".cache" / "huggingface"),
}


def test_import_configures_offline_without_loading_or_io():
    # A fresh process catches eager ML imports even when other tests imported them.
    result = subprocess.run(
        [sys.executable, "-c", """
import builtins
import os
from pathlib import Path
import cv2

def forbidden(*args, **kwargs):
    raise AssertionError('Import attempted model/video/directory work')

real_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name.split('.')[0] in {'torch', 'transformers', 'huggingface_hub'}:
        raise AssertionError('ML dependencies must be lazy: ' + name)
    return real_import(name, *args, **kwargs)

cv2.VideoCapture = forbidden
Path.mkdir = forbidden
os.mkdir = forbidden
builtins.__import__ = guarded_import
import activity_recognition
assert os.environ['HF_HUB_OFFLINE'] == '1'
assert os.environ['TRANSFORMERS_OFFLINE'] == '1'
assert os.environ['HF_HOME'] == str(Path(activity_recognition.__file__).parent / '.cache' / 'huggingface')
"""],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_configure_local_runtime_overrides_external_settings(monkeypatch):
    ar = importlib.import_module("activity_recognition")
    for key in OFFLINE_ENV:
        monkeypatch.setenv(key, "external-setting")

    ar.configure_local_runtime()

    assert {key: os.environ[key] for key in OFFLINE_ENV} == OFFLINE_ENV


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    ar = importlib.import_module("activity_recognition")
    if hasattr(ar, "get_recognizer"):
        ar.get_recognizer.cache_clear()
    events = []
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")
    state = SimpleNamespace(
        frames=32, processor_error=None, model_error=None, transfer_error=None,
        snapshot_error=None, events=events, snapshot=snapshot,
    )

    def resolve(**kwargs):
        events.append(("snapshot", kwargs))
        if state.snapshot_error:
            raise state.snapshot_error
        return str(snapshot)

    class FakeModel:
        def __init__(self):
            self.config = SimpleNamespace(vision_config=SimpleNamespace(num_frames=state.frames))
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
    transformers.XCLIPModel = ModelFactory
    transformers.XCLIPProcessor = ProcessorFactory
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", resolve)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.cuda, "synchronize", lambda device: events.append(("sync", device)))
    monkeypatch.setattr(ar, "perf_counter", lambda: events.append(("clock",)) or float(len(events)), raising=False)
    yield ar, state
    if hasattr(ar, "get_recognizer"):
        ar.get_recognizer.cache_clear()


@pytest.mark.parametrize("device", ["cpu", "auto"])
def test_cpu_initialization_pins_local_safetensors_and_eval(runtime, device):
    ar, state = runtime

    recognizer = ar.XCLIPRecognizer(device)

    assert recognizer.device == torch.device("cpu")
    assert recognizer.dtype == torch.float32
    assert recognizer.model_revision == REVISION
    assert recognizer.processor.snapshot == str(state.snapshot)
    assert recognizer.model.device == recognizer.device
    assert recognizer.model.training is False
    assert isinstance(recognizer.load_time_seconds, float)
    assert recognizer.load_time_seconds > 0
    assert ("snapshot", {
        "repo_id": "microsoft/xclip-base-patch16-zero-shot",
        "revision": REVISION,
        "cache_dir": PROJECT_DIR / ".cache" / "huggingface" / "hub",
        "local_files_only": True,
    }) in state.events
    processor = next(event for event in state.events if event[0] == "processor")
    assert processor[1] == str(state.snapshot)
    assert processor[2]["local_files_only"] is True
    model = next(event for event in state.events if event[0] == "model")
    assert model[1] == str(state.snapshot)
    assert model[2] == {
        "local_files_only": True, "use_safetensors": True,
        "trust_remote_code": False, "dtype": torch.float32,
        "attn_implementation": "eager",
    }
    assert not any(event[0] == "sync" for event in state.events)


@pytest.mark.parametrize("device", ["auto", "cuda", "cuda:0"])
def test_cuda_uses_half_precision_and_times_completed_initialization(runtime, monkeypatch, device):
    ar, state = runtime
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)

    recognizer = ar.XCLIPRecognizer(device)

    assert recognizer.device.type == "cuda"
    assert recognizer.dtype == torch.float16
    assert recognizer.model.device == recognizer.device
    assert recognizer.model.training is False
    model_event = next(event for event in state.events if event[0] == "model")
    assert model_event[2]["dtype"] == torch.float16
    assert "torch_dtype" not in model_event[2]
    assert state.events[-3:] == [("eval",), ("sync", recognizer.device), ("clock",)]
    assert recognizer.load_time_seconds > 0


def test_explicit_cpu_overrides_available_cuda(runtime, monkeypatch):
    ar, _ = runtime
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)

    recognizer = ar.XCLIPRecognizer("cpu")

    assert recognizer.device == torch.device("cpu")
    assert recognizer.dtype == torch.float32


def test_explicit_cuda_unavailable_is_actionable_before_loading(runtime):
    ar, state = runtime

    with pytest.raises(RuntimeError, match="(?i)cuda.*cpu"):
        ar.XCLIPRecognizer("cuda")

    assert not any(event[0] == "snapshot" for event in state.events)


def test_cuda_transfer_failure_does_not_retry_on_cpu(runtime, monkeypatch):
    ar, state = runtime
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    state.transfer_error = torch.OutOfMemoryError("test GPU allocation failure")

    with pytest.raises(torch.OutOfMemoryError, match="test GPU allocation failure"):
        ar.XCLIPRecognizer()

    assert [event[1].type for event in state.events if event[0] == "to"] == ["cuda"]


def test_checkpoint_must_use_native_32_frames(runtime):
    ar, state = runtime
    state.frames = 8

    with pytest.raises(RuntimeError, match="32"):
        ar.XCLIPRecognizer()


@pytest.mark.parametrize("failure", ["snapshot_error", "processor_error", "model_error"])
def test_missing_or_incomplete_cache_has_download_command_and_cause(runtime, failure):
    ar, state = runtime
    error = (LocalEntryNotFoundError("missing cached revision") if failure == "snapshot_error"
             else OSError("missing local asset"))
    setattr(state, failure, error)

    with pytest.raises(RuntimeError, match=r"uv run --locked python download_model\.py") as exc:
        ar.XCLIPRecognizer()

    assert exc.value.__cause__ is error


@pytest.mark.parametrize("present_asset", [None, "vocab.json", "merges.txt"])
def test_real_partial_tokenizer_snapshot_has_actionable_error(monkeypatch, tmp_path, present_asset):
    ar = importlib.import_module("activity_recognition")
    from transformers import VideoMAEImageProcessor, XCLIPProcessor

    VideoMAEImageProcessor().save_pretrained(tmp_path)
    (tmp_path / "tokenizer_config.json").write_text(
        '{"tokenizer_class": "CLIPTokenizer"}', encoding="utf-8",
    )
    assets = {
        "vocab.json": '{"<|startoftext|>": 0, "<|endoftext|>": 1}',
        "merges.txt": "#version: 0.2\n",
    }
    if present_asset:
        (tmp_path / present_asset).write_text(assets[present_asset], encoding="utf-8")

    # Reproduce the installed processor's slow-tokenizer fallback, without weights.
    with pytest.raises((TypeError, ImportError)) as raw:
        XCLIPProcessor.from_pretrained(tmp_path, local_files_only=True)
    # Without optional protobuf, Transformers masks the original TypeError.
    missing_asset_error = raw.value.__context__ if isinstance(raw.value, ImportError) else raw.value
    assert isinstance(missing_asset_error, TypeError)
    assert "not NoneType" in str(missing_asset_error)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda **kwargs: str(tmp_path))
    with pytest.raises(RuntimeError, match=r"uv run --locked python download_model\.py") as exc:
        ar.XCLIPRecognizer("cpu")

    assert isinstance(exc.value.__cause__, FileNotFoundError)
    missing = "merges.txt" if present_asset == "vocab.json" else "vocab.json"
    assert missing in str(exc.value.__cause__)


@pytest.mark.parametrize("failure", ["processor_error", "model_error"])
def test_unrelated_loader_typeerror_is_not_disguised_as_cache_failure(runtime, failure):
    ar, state = runtime
    error = TypeError("unrelated loader programming error")
    setattr(state, failure, error)

    with pytest.raises(TypeError) as exc:
        ar.XCLIPRecognizer("cpu")

    assert exc.value is error


def test_slow_tokenizer_asset_pair_is_accepted(runtime):
    ar, state = runtime
    (state.snapshot / "tokenizer.json").unlink()
    (state.snapshot / "vocab.json").write_text("{}", encoding="utf-8")
    (state.snapshot / "merges.txt").write_text("#version: 0.2\n", encoding="utf-8")

    recognizer = ar.XCLIPRecognizer("cpu")

    assert recognizer.processor.snapshot == str(state.snapshot)
    assert recognizer.model.training is False


def test_cached_recognizer_reuses_initialized_model(runtime):
    ar, state = runtime

    first = ar.get_recognizer()
    second = ar.get_recognizer()

    assert first is second
    assert first.model.training is False
    assert sum(event[0] == "model" for event in state.events) == 1
    assert ar.get_recognizer.cache_info().maxsize == 1


@pytest.mark.parametrize("available", [False, True])
def test_device_info_reports_torch_and_actual_memory(runtime, monkeypatch, available):
    ar, _ = runtime
    monkeypatch.setattr(torch.cuda, "is_available", lambda: available)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda device: "Test GTX 1650")
    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda device: SimpleNamespace(total_memory=4095 * 2**20))
    monkeypatch.setattr(torch.cuda, "mem_get_info", lambda device: (3000 * 2**20, 4095 * 2**20))

    info = ar.device_info()

    assert info == {
        "device": "cuda" if available else "cpu",
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "cuda_available": available,
        "gpu_name": "Test GTX 1650" if available else None,
        "total_vram_mib": 4095.0 if available else None,
        "free_vram_mib": 3000.0 if available else None,
    }


def test_download_import_has_no_side_effects(monkeypatch):
    path = PROJECT_DIR / "download_model.py"
    assert path.is_file(), "Explicit download entry point is missing"
    before = dict(os.environ)

    def forbidden(**kwargs):
        pytest.fail("Import must not download")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", forbidden)
    namespace = runpy.run_path(str(path))

    assert callable(namespace["main"])
    assert dict(os.environ) == before


def test_explicit_download_enables_online_only_for_pinned_assets(monkeypatch, capsys):
    path = PROJECT_DIR / "download_model.py"
    assert path.is_file(), "Explicit download entry point is missing"
    for key in OFFLINE_ENV:
        monkeypatch.setenv(key, "external-setting")
    calls = []

    def download(**kwargs):
        assert {key: os.environ[key] for key in OFFLINE_ENV} == {
            **OFFLINE_ENV, "HF_HUB_OFFLINE": "0", "TRANSFORMERS_OFFLINE": "0",
        }
        calls.append(kwargs)
        return "/fake/pinned-snapshot"

    monkeypatch.setattr(huggingface_hub, "snapshot_download", download)
    runpy.run_path(str(path), run_name="__main__")

    assert calls == [{
        "repo_id": "microsoft/xclip-base-patch16-zero-shot",
        "revision": REVISION,
        "cache_dir": PROJECT_DIR / ".cache" / "huggingface" / "hub",
        "allow_patterns": ["*.json", "merges.txt", "model.safetensors"],
    }]
    output = capsys.readouterr().out
    assert REVISION in output
    assert "/fake/pinned-snapshot" in output
