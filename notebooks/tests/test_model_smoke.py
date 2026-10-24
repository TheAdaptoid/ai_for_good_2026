"""Opt-in, checkpoint-backed acceptance on synthetic clips, not accuracy tests."""

import gc
import json
import os
import socket

import pytest


pytestmark = [
    pytest.mark.model_smoke,
    pytest.mark.skipif(
        os.environ.get("RUN_XCLIP_SMOKE") != "1",
        reason="Set RUN_XCLIP_SMOKE=1 to use the pinned local checkpoint",
    ),
]

REVISION = "6746d6a5202bf24300cd9bf36f457f174483d41b"
INITIAL_LABELS = {
    "dancing": "Dancing",
    "singing": "Singing",
    "playing_sports": "Playing sports",
    "playing_games": "Playing games",
    "running": "Running",
    "walking": "Walking",
    "sitting_and_listening": "Sitting and listening",
    "drawing_or_painting": "Drawing or painting",
    "other_activities": "Other activities",
}


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_cached_checkpoint_offline_native_frames(device, monkeypatch, tmp_path, make_video):
    # Import the runtime before HF so its offline/telemetry policy takes effect.
    import activity_recognition as ar
    import cv2
    import numpy as np
    import torch

    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable; this skip does not satisfy GPU acceptance")

    attempts = []

    def deny_network(*args, **kwargs):
        attempts.append("connect")
        raise AssertionError("Model initialization/inference attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"

    path = tmp_path / "synthetic-12s.mp4" if device == "cuda" else make_video()
    labels = INITIAL_LABELS if device == "cuda" else {"dancing": "Dancing", "walking": "Walking"}
    duration = 12.0 if device == "cuda" else 2.0
    previous_threads = torch.get_num_threads()
    recognizer = None
    try:
        if device == "cpu":
            torch.set_num_threads(4)
        else:
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (96, 64),
            )
            try:
                assert writer.isOpened(), "mp4v writer unavailable; MP4 acceptance is required"
                for index in range(360):
                    frame = np.zeros((64, 96, 3), dtype=np.uint8)
                    x = index % 72
                    frame[20:44, x:x + 24] = (0, 0, 255)
                    writer.write(frame)
            finally:
                writer.release()
            capture = cv2.VideoCapture(str(path))
            try:
                assert capture.isOpened()
                assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 360
                assert capture.get(cv2.CAP_PROP_FPS) == pytest.approx(30.0)
                ok, frame = capture.read()
                assert ok and frame.shape == (64, 96, 3)
            finally:
                capture.release()

        recognizer = ar.XCLIPRecognizer(device=device)
        assert recognizer.model.config.vision_config.num_frames == 32
        assert recognizer.model.training is False
        parameter = next(recognizer.model.parameters())
        assert parameter.device.type == device
        assert parameter.dtype == (torch.float16 if device == "cuda" else torch.float32)
        del parameter

        results = [recognizer.classify(str(path), list(labels.values())) for _ in range(2)]
        for result in results:
            assert json.loads(json.dumps(result, allow_nan=False)) == result
            assert result["model"] == "microsoft/xclip-base-patch16-zero-shot"
            assert result["model_revision"] == REVISION
            assert result["device"] == device
            assert result["dtype"] == ("torch.float16" if device == "cuda" else "torch.float32")
            assert result["num_frames"] == result["unique_sampled_frames"] == 32
            assert len(result["sampled_frame_indices"]) == 32
            assert result["sampled_frame_indices"][0] == 0
            assert result["sampled_frame_indices"][-1] == (359 if device == "cuda" else 59)
            assert result["clip_start"] == 0.0
            assert result["clip_end"] == pytest.approx(duration)
            assert result["labels"] == labels
            assert set(result["scores"]) == set(result["logits"]) == set(labels)
            assert all(0 <= score <= 1 for score in result["scores"].values())
            assert sum(result["scores"].values()) == pytest.approx(1.0, abs=1e-6)
            assert result["activity"] == max(result["scores"], key=result["scores"].get)
            assert 0 < result["inference_time_seconds"] <= result["total_time_seconds"]
            assert 0 < result["preprocessing_time_seconds"] <= result["total_time_seconds"]
            allocated = result["peak_gpu_memory_allocated_mib"]
            reserved = result["peak_gpu_memory_reserved_mib"]
            if device == "cuda":
                assert 0 < allocated <= reserved
            else:
                assert allocated is reserved is None
        assert results[0]["activity"] == results[1]["activity"]
        assert results[0]["scores"] == pytest.approx(results[1]["scores"], abs=1e-5)
        assert attempts == []
        measured = results[1]
        print("\nSYNTHETIC_MODEL_SMOKE " + json.dumps({
            "device": device, "dtype": measured["dtype"], "clip_seconds": duration,
            "container": path.suffix, "candidates": len(labels), "num_frames": 32,
            "load_seconds": recognizer.load_time_seconds,
            "inference_seconds": measured["inference_time_seconds"],
            "total_seconds": measured["total_time_seconds"],
            "peak_allocated_mib": measured["peak_gpu_memory_allocated_mib"],
            "peak_reserved_mib": measured["peak_gpu_memory_reserved_mib"],
            "network_attempts": len(attempts), "runtime": ar.device_info(),
        }, allow_nan=False))
    finally:
        recognizer = None
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()
        torch.set_num_threads(previous_threads)
        path.unlink(missing_ok=True)
