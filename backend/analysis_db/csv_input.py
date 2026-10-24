import csv
import math
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TextIO

from analysis_db.contracts import CsvImportError, DataError, DetectionRow

HEADER_SAMPLE_BYTES = 64 * 1024
SQLITE_INT64_MAX = 2**63 - 1
REQUIRED_COLUMNS = (
    "video_title",
    "video_filename",
    "frame_number",
    "frame_id",
    "person_id",
    "source_time_seconds",
    "face_bbox_x1",
    "face_bbox_y1",
    "face_bbox_x2",
    "face_bbox_y2",
    "det_score",
)
SELECTED_SUFFIXES = {".csv", ".tsv"}


def discover_inputs(path: Path) -> tuple[list[Path], list[Path]]:
    if path.is_file():
        return [path], []
    if not path.is_dir():
        raise DataError(f"Input path does not exist: {path}")
    entries = sorted(path.iterdir())
    selected = [
        entry for entry in entries
        if entry.is_file() and entry.suffix.lower() in SELECTED_SUFFIXES
    ]
    if not selected:
        raise DataError(f"No CSV/TSV sources found in directory: {path}")
    selected_set = set(selected)
    ignored = [entry for entry in entries if entry not in selected_set]
    return selected, ignored


def _sniff_delimiter(handle: TextIO, source: Path) -> str:
    try:
        sample = handle.read(HEADER_SAMPLE_BYTES)
    except UnicodeDecodeError as exc:
        raise CsvImportError(source, 1, f"invalid UTF-8 in header sample: {exc}") from exc
    except OSError as exc:
        raise CsvImportError(source, None, f"could not read source: {exc}") from exc
    handle.seek(0)
    if sample.count(",") and not sample.count("\t"):
        return ","
    if sample.count("\t") and not sample.count(","):
        return "\t"
    return "\t" if source.suffix.lower() == ".tsv" else ","


def iter_rows(source: Path) -> Iterator[DetectionRow]:
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        delimiter = _sniff_delimiter(handle, source)
        reader = csv.reader(handle, delimiter=delimiter, strict=True)
        try:
            header = next(reader)
        except StopIteration:
            raise CsvImportError(source, None, "source is empty: no header row") from None
        except csv.Error as exc:
            raise CsvImportError(
                source, max(reader.line_num, 1), f"malformed header record: {exc}"
            ) from exc
        except UnicodeDecodeError as exc:
            raise CsvImportError(
                source, max(reader.line_num, 1), f"invalid UTF-8: {exc}"
            ) from exc
        except OSError as exc:
            raise CsvImportError(source, None, f"could not read source: {exc}") from exc
        header_counts = Counter(header)
        duplicates = sorted(name for name, count in header_counts.items() if count > 1)
        if duplicates:
            raise CsvImportError(
                source, max(reader.line_num, 1),
                "duplicate header column(s): " + ", ".join(duplicates),
            )
        missing = [name for name in REQUIRED_COLUMNS if name not in header_counts]
        if missing:
            raise CsvImportError(
                source, max(reader.line_num, 1),
                "missing required header column(s): " + ", ".join(missing),
            )
        while True:
            start_line = reader.line_num + 1
            try:
                fields = next(reader)
            except StopIteration:
                return
            except csv.Error as exc:
                raise CsvImportError(
                    source, start_line, f"malformed record: {exc}"
                ) from exc
            except UnicodeDecodeError as exc:
                raise CsvImportError(
                    source, start_line, f"invalid UTF-8: {exc}"
                ) from exc
            except OSError as exc:
                raise CsvImportError(source, None, f"could not read source: {exc}") from exc
            if not fields:
                continue
            if len(fields) != len(header):
                raise CsvImportError(
                    source, start_line,
                    f"record starts with {len(fields)} cells; header defines {len(header)}",
                )
            yield validate_row(dict(zip(header, fields)), source=source, line_number=start_line)


def finite_number(values: Mapping[str, str], column: str) -> float:
    try:
        number = float(values[column])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{column} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{column} must be finite")
    return number


def validate_row(values: Mapping[str, str], *, source: Path, line_number: int) -> DetectionRow:
    try:
        raw_number = values["frame_number"]
        if not re.fullmatch(r"[0-9]+", raw_number) or not 0 <= int(raw_number) <= SQLITE_INT64_MAX:
            raise ValueError("frame_number must be a nonnegative SQLite integer")
        frame_number = int(raw_number)
        for name in ("frame_id", "person_id", "video_filename"):
            if not values[name].strip():
                raise ValueError(f"{name} must be nonempty")
        timestamp = finite_number(values, "source_time_seconds")
        if timestamp < 0:
            raise ValueError("source_time_seconds must be nonnegative")
        x1, y1, x2, y2 = (finite_number(values, name) for name in (
            "face_bbox_x1", "face_bbox_y1", "face_bbox_x2", "face_bbox_y2"))
        if not x1 < x2:
            raise ValueError("face_bbox_x1 must be less than face_bbox_x2")
        if not y1 < y2:
            raise ValueError("face_bbox_y1 must be less than face_bbox_y2")
        score = finite_number(values, "det_score")
        if not 0 <= score <= 1:
            raise ValueError("det_score must be between 0 and 1")
        return DetectionRow(
            line_number=line_number,
            video_title=values["video_title"],
            video_filename=values["video_filename"],
            frame_number=frame_number,
            frame_id=values["frame_id"],
            person_id=values["person_id"],
            source_time_seconds=timestamp,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            det_score=score,
        )
    except KeyError as exc:
        raise CsvImportError(source, line_number, f"missing required field: {exc}") from exc
    except ValueError as exc:
        raise CsvImportError(source, line_number, str(exc)) from exc
