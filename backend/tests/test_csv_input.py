import csv

import pytest

from analysis_db.contracts import CsvImportError, DataError
from analysis_db.csv_input import discover_inputs, iter_rows

HEADERS = ["video_title", "video_filename", "frame_number", "frame_id", "person_id",
           "source_time_seconds", "face_bbox_x1", "face_bbox_y1", "face_bbox_x2",
           "face_bbox_y2", "det_score"]
VALID = ["Clip", "clip.mp4", "0", "frame-0", "person-1", "0", "1", "2", "10", "20", "0.9"]


def _write(tmp_path, name, headers, *rows, encoding="utf-8"):
    path = tmp_path / name
    with path.open("w", newline="", encoding=encoding) as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
    return path


def _row_with(tmp_path, name, **overrides):
    values = dict(zip(HEADERS, VALID))
    values.update(overrides)
    path = _write(tmp_path, name, HEADERS, [values[column] for column in HEADERS])
    return path


@pytest.mark.parametrize("delimiter,suffix", [(",", ".csv"), ("\t", ".csv"), ("\t", ".tsv")])
def test_delimiters_and_preserved_values(tmp_path, delimiter, suffix):
    path = tmp_path / ("source" + suffix)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(HEADERS)
        writer.writerow(VALID)
    row, = iter_rows(path)
    assert row.frame_id == "frame-0"
    assert row.person_id == "person-1"
    assert row.x1 == 1.0 and row.det_score == 0.9 and row.line_number == 2


@pytest.mark.parametrize("column,value", [
    ("frame_id", " "), ("person_id", ""), ("frame_number", "-1"),
    ("frame_number", "1.5"), ("frame_number", "1.0"),
    ("source_time_seconds", "-0.1"), ("source_time_seconds", "nan"),
    ("face_bbox_x2", "1"), ("face_bbox_y2", "2"), ("face_bbox_x1", "inf"),
    ("det_score", "1.1"), ("det_score", "-0.1"), ("det_score", "NaN"),
])
def test_invalid_value_has_source_and_line(tmp_path, column, value):
    path = tmp_path / "bad.csv"
    values = dict(zip(HEADERS, VALID))
    values[column] = value
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, HEADERS)
        writer.writeheader()
        writer.writerow(values)
    with pytest.raises(CsvImportError) as caught:
        list(iter_rows(path))
    assert caught.value.source == path
    assert caught.value.line_number == 2
    assert column in caught.value.reason


def test_missing_required_headers(tmp_path):
    headers = [name for name in HEADERS if name != "det_score"]
    path = _write(tmp_path, "headers.csv", headers, VALID[: len(headers)])
    with pytest.raises(CsvImportError) as caught:
        list(iter_rows(path))
    assert caught.value.source == path
    assert "det_score" in caught.value.reason


def test_duplicate_headers(tmp_path):
    path = _write(tmp_path, "dup.csv", HEADERS[:-1] + ["frame_id", "det_score"],
                  VALID[:-1] + ["frame-0", "0.9"])
    with pytest.raises(CsvImportError) as caught:
        list(iter_rows(path))
    assert caught.value.source == path
    assert "frame_id" in caught.value.reason


def test_extra_record_cells(tmp_path):
    path = _write(tmp_path, "extra.csv", HEADERS, VALID + ["face.png"])
    with pytest.raises(CsvImportError) as caught:
        list(iter_rows(path))
    assert caught.value.source == path
    assert caught.value.line_number == 2


def test_missing_record_cells(tmp_path):
    path = _write(tmp_path, "short.csv", HEADERS, VALID[:-1])
    with pytest.raises(CsvImportError) as caught:
        list(iter_rows(path))
    assert caught.value.source == path
    assert caught.value.line_number == 2


def test_quoted_filename_with_commas(tmp_path):
    path = _row_with(tmp_path, "commas.csv", video_filename="fall 2024, take 2.png")
    row, = iter_rows(path)
    assert row.video_filename == "fall 2024, take 2.png"


def test_optional_image_columns_are_ignored(tmp_path):
    headers = HEADERS + ["face_image_path", "frame_image_path"]
    values = VALID + ["/img/f0.jpg", "/img/f0.png"]
    path = _write(tmp_path, "images.csv", headers, values)
    row, = iter_rows(path)
    assert row.frame_id == "frame-0"
    assert not hasattr(row, "face_image_path")
    assert not hasattr(row, "frame_image_path")


def test_header_only_success(tmp_path):
    path = _write(tmp_path, "header_only.csv", HEADERS)
    assert list(iter_rows(path)) == []


def test_zero_byte_source(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    with pytest.raises(CsvImportError) as caught:
        list(iter_rows(path))
    assert caught.value.source == path
    assert caught.value.line_number is None


def test_malformed_quoting(tmp_path):
    path = tmp_path / "quoting.csv"
    path.write_bytes((",".join(HEADERS) + "\n" + '"Clip, unclosed' + "\n").encode("utf-8"))
    with pytest.raises(CsvImportError) as caught:
        list(iter_rows(path))
    assert caught.value.source == path
    assert caught.value.line_number == 2


def test_ids_with_spaces_preserved(tmp_path):
    path = _row_with(tmp_path, "spaces.csv", frame_id=" frame-0 ", person_id=" person 7 ")
    row, = iter_rows(path)
    assert row.frame_id == " frame-0 "
    assert row.person_id == " person 7 "


def test_empty_title_allowed(tmp_path):
    path = _row_with(tmp_path, "title.csv", video_title="")
    row, = iter_rows(path)
    assert row.video_title == ""


def test_frame_number_bounds(tmp_path):
    path = _row_with(tmp_path, "big.csv", frame_number="9223372036854775808")
    with pytest.raises(CsvImportError) as caught:
        list(iter_rows(path))
    assert caught.value.source == path
    assert caught.value.line_number == 2
    assert "frame_number" in caught.value.reason


def test_frame_number_at_sqlite_max(tmp_path):
    path = _row_with(tmp_path, "boundary.csv", frame_number="9223372036854775807")
    row, = iter_rows(path)
    assert row.frame_number == 9223372036854775807


def test_streaming_yields_before_invalid(tmp_path):
    bad = dict(zip(HEADERS, VALID))
    bad["det_score"] = "1.5"
    path = _write(tmp_path, "stream.csv", HEADERS, VALID, [bad[c] for c in HEADERS])
    rows = iter_rows(path)
    first = next(rows)
    assert first.line_number == 2 and first.det_score == 0.9
    with pytest.raises(CsvImportError) as caught:
        next(rows)
    assert caught.value.source == path
    assert caught.value.line_number == 3


def test_discover_directory_selection_is_deterministic(tmp_path):
    (tmp_path / "z.csv").write_bytes(b",\n")
    (tmp_path / "M.TSV").write_bytes(b"\t\n")
    (tmp_path / "early.CSV").write_bytes(b",\n")
    (tmp_path / "notes.txt").write_bytes(b"")
    (tmp_path / "i.png").write_bytes(b"")
    (tmp_path / "log.csvx").write_bytes(b"")
    (tmp_path / "nested").mkdir()
    selected, ignored = discover_inputs(tmp_path)
    assert selected == [tmp_path / "M.TSV", tmp_path / "early.CSV", tmp_path / "z.csv"]
    assert ignored == [tmp_path / "i.png", tmp_path / "log.csvx",
                       tmp_path / "nested", tmp_path / "notes.txt"]


def test_discover_explicit_file_any_extension(tmp_path):
    path = tmp_path / "rows.dat"
    path.write_bytes(b"")
    selected, ignored = discover_inputs(path)
    assert selected == [path]
    assert ignored == []


def test_discover_missing_path(tmp_path):
    with pytest.raises(DataError):
        discover_inputs(tmp_path / "gone")


def test_discover_directory_without_candidates(tmp_path):
    (tmp_path / "notes.txt").write_bytes(b"")
    with pytest.raises(DataError):
        discover_inputs(tmp_path)
