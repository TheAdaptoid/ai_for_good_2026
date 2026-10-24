import json
import subprocess

import pytest
from analysis_db.contracts import DataError, VideoMetadata
from analysis_db.video_metadata import parse_probe, probe_video, resolve_video


def test_metadata_uses_video_stream_and_rational_fps():
    payload = {"streams": [
        {"codec_type": "audio", "duration": "999"},
        {"codec_type": "video", "duration": "2.5", "avg_frame_rate": "30000/1001",
         "width": 1920, "height": 1080, "tags": {"creation_time": "2025-01-01T12:00:00Z"}},
    ], "format": {"duration": "3.0"}}
    result = parse_probe(payload)
    assert result.duration_seconds == 2.5
    assert result.fps == pytest.approx(30000 / 1001)
    assert (result.width, result.height) == (1920, 1080)
    assert result.created_at == "2025-01-01T12:00:00Z"


def test_absent_metadata_stays_absent():
    assert parse_probe({"streams": [{"codec_type": "video"}]}) == VideoMetadata()


def test_probe_argument_list_preserves_filename(tmp_path, monkeypatch):
    path = tmp_path / "clip with spaces.mp4"
    path.touch()
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(args=args, kwargs=kwargs)
        return subprocess.CompletedProcess(args, 0, json.dumps({"streams": [{"codec_type": "video"}]}), "")

    monkeypatch.setattr("analysis_db.video_metadata.subprocess.run", fake_run)
    assert probe_video(path) == VideoMetadata()
    assert seen["args"][-1] == str(path)
    assert seen["args"][0] == "ffprobe"
    assert seen["kwargs"].get("shell", False) is False
    assert seen["kwargs"]["timeout"] == 60


# --- resolve_video ---


def test_resolve_returns_existing_resolved_file(tmp_path):
    path = tmp_path / "clip.mp4"
    path.touch()
    assert resolve_video("clip.mp4", tmp_path) == path.resolve()


def test_missing_file_raises(tmp_path):
    with pytest.raises(DataError):
        resolve_video("absent.mp4", tmp_path)


def test_different_case_is_not_found(tmp_path):
    (tmp_path / "Clip.MP4").touch()
    with pytest.raises(DataError):
        resolve_video("clip.mp4", tmp_path)


@pytest.mark.parametrize(
    "filename",
    ["", "   ", ".", "..", "sub/clip.mp4", "C:\\clip.mp4", "..\\clip.mp4", "clip/../clip.mp4"],
)
def test_non_basename_names_rejected(tmp_path, filename):
    (tmp_path / "clip.mp4").touch()
    with pytest.raises(DataError):
        resolve_video(filename, tmp_path)


# --- parse_probe ---


def test_absent_streams_raises():
    with pytest.raises(DataError):
        parse_probe({"format": {"duration": "1.0"}})


def test_streams_not_a_list_raises():
    with pytest.raises(DataError):
        parse_probe({"streams": {"codec_type": "video"}})


def test_audio_only_payload_raises():
    with pytest.raises(DataError):
        parse_probe({"streams": [{"codec_type": "audio"}], "format": {"duration": "3.0"}})


def test_only_attached_pic_streams_raises():
    payload = {"streams": [{"codec_type": "video", "disposition": {"attached_pic": 1}}]}
    with pytest.raises(DataError):
        parse_probe(payload)


def test_attached_pic_stream_is_skipped_for_real_stream():
    payload = {"streams": [
        {"codec_type": "video", "disposition": {"attached_pic": 1},
         "duration": "1.0", "avg_frame_rate": "1/1", "width": 300, "height": 300},
        {"codec_type": "video", "duration": "2.0", "avg_frame_rate": "25/1",
         "width": 1920, "height": 1080},
    ]}
    result = parse_probe(payload)
    assert result.duration_seconds == 2.0
    assert result.fps == 25.0
    assert (result.width, result.height) == (1920, 1080)


def test_zero_avg_frame_rate_falls_back_to_r_frame_rate():
    payload = {"streams": [{
        "codec_type": "video",
        "avg_frame_rate": "0/0",
        "r_frame_rate": "30000/1001",
    }]}
    assert parse_probe(payload).fps == pytest.approx(30000 / 1001)


def test_format_duration_and_creation_time_fallback():
    payload = {"streams": [{"codec_type": "video"}],
               "format": {"duration": "12.75", "tags": {"creation_time": "2024-06-01T00:00:00Z"}}}
    result = parse_probe(payload)
    assert result.duration_seconds == 12.75
    assert result.created_at == "2024-06-01T00:00:00Z"


def test_stream_creation_time_wins_over_format():
    payload = {"streams": [{"codec_type": "video", "tags": {"creation_time": "2025-05-05T05:05:05Z"}}],
               "format": {"tags": {"creation_time": "2024-01-01T00:00:00Z"}}}
    assert parse_probe(payload).created_at == "2025-05-05T05:05:05Z"


def test_empty_creation_time_is_ignored():
    payload = {"streams": [{"codec_type": "video", "tags": {"creation_time": "  "}}],
               "format": {"tags": {"creation_time": "2024-01-01T00:00:00Z"}}}
    assert parse_probe(payload).created_at == "2024-01-01T00:00:00Z"


@pytest.mark.parametrize(
    "stream",
    [
        {"codec_type": "video", "duration": "N/A", "avg_frame_rate": "N/A",
         "r_frame_rate": "N/A", "width": "N/A", "height": "N/A"},
        {"codec_type": "video", "duration": "NaN", "avg_frame_rate": "0/0",
         "r_frame_rate": "0/0", "width": 0, "height": 0},
        {"codec_type": "video", "duration": "Infinity", "avg_frame_rate": "-25/1",
         "r_frame_rate": "0/1", "width": -1920, "height": 1080.5},
        {"codec_type": "video", "duration": -1, "avg_frame_rate": "0/1",
         "r_frame_rate": "-0/1", "width": True, "height": True},
    ],
)
def test_unclean_optional_fields_become_null(stream):
    assert parse_probe({"streams": [stream]}) == VideoMetadata()


def test_integer_string_dimensions_accepted():
    payload = {"streams": [{"codec_type": "video", "width": "1920", "height": "1080"}]}
    assert parse_probe(payload) == VideoMetadata(width=1920, height=1080)


# --- probe_video ---


def test_timeout_becomes_data_error(tmp_path, monkeypatch):
    (tmp_path / "clip.mp4").touch()

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 60)

    monkeypatch.setattr("analysis_db.video_metadata.subprocess.run", fake_run)
    with pytest.raises(DataError):
        probe_video(tmp_path / "clip.mp4")


def test_missing_ffprobe_becomes_data_error(tmp_path, monkeypatch):
    (tmp_path / "clip.mp4").touch()

    def fake_run(args, **kwargs):
        raise OSError("ffprobe not found")

    monkeypatch.setattr("analysis_db.video_metadata.subprocess.run", fake_run)
    with pytest.raises(DataError):
        probe_video(tmp_path / "clip.mp4")


def test_nonzero_status_becomes_data_error_with_stderr(tmp_path, monkeypatch):
    (tmp_path / "clip.mp4").touch()

    def fake_run(args, **kwargs):
        raise subprocess.CalledProcessError(1, args, stderr="moov atom not found")

    monkeypatch.setattr("analysis_db.video_metadata.subprocess.run", fake_run)
    with pytest.raises(DataError):
        probe_video(tmp_path / "clip.mp4")


@pytest.mark.parametrize("stdout", ["not json", "[1, 2]", '"text"'])
def test_bad_json_output_becomes_data_error(tmp_path, monkeypatch, stdout):
    (tmp_path / "clip.mp4").touch()

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr("analysis_db.video_metadata.subprocess.run", fake_run)
    with pytest.raises(DataError):
        probe_video(tmp_path / "clip.mp4")
