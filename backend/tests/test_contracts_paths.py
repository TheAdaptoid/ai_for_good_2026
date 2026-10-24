from pathlib import Path
import pytest
from analysis_db.contracts import CsvImportError, DataError, FileResult, VideoMetadata
from analysis_db.paths import DEFAULT_DB, DEFAULT_VIDEO_DIR, repository_relative


def test_defaults_ignore_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert DEFAULT_DB.is_absolute()
    assert DEFAULT_VIDEO_DIR.is_absolute()
    assert DEFAULT_DB.parts[-2:] == ("data", "analysis.sqlite")
    assert DEFAULT_VIDEO_DIR.parts[-2:] == ("data", "videos")


def test_repository_path_policy(tmp_path):
    inside = tmp_path / "data" / "videos" / "clip.mp4"
    assert repository_relative(inside, root=tmp_path) == "data/videos/clip.mp4"
    with pytest.raises(DataError, match="repository"):
        repository_relative(tmp_path.parent / "outside.mp4", root=tmp_path)


def test_result_counters_are_independent():
    one, two = FileResult(Path("one.csv")), FileResult(Path("two.csv"))
    one.inserted["Video"] = 1
    assert two.inserted["Video"] == 0
    assert VideoMetadata().fps is None
    assert "one.csv:3: invalid score" == str(CsvImportError(Path("one.csv"), 3, "invalid score"))
