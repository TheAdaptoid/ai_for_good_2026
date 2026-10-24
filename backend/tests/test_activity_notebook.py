from contextlib import closing
from importlib import util
import json
import os
from pathlib import Path
import random as _random
import subprocess
import sys

import nbformat
import pytest
from jupyter_client.kernelspec import KernelSpecManager
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

from analysis_db.storage import connect_database, table_counts

BACKEND = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = BACKEND / "notebooks" / "activity_classification.ipynb"

ACTIVITIES = [
    "Dancing", "Rapping", "Singing", "Playing sports", "Playing games",
    "Running", "Walking", "Sitting and listening", "Drawing or painting",
]
TOP_LABEL = "Dancing"
ROW_KEYS = sorted([
    "detection_id", "condition", "num_frames", "predictions",
    "reference_label", "reference_rank", "reference_score", "top1_correct",
    "top3_correct", "retrieval_time_seconds", "preprocessing_time_seconds",
    "inference_time_seconds", "source_span_seconds", "unique_frame_count",
    "left_padding_count", "right_padding_count",
])
SUMMARY_KEYS = sorted([
    "condition", "evaluated_detections", "top1_accuracy", "top3_accuracy",
    "excluded",
])
RESULT_JSON_PREFIX = "RESULT_JSON:"
SAMPLING_KEYS = sorted([
    "num_frames", "retrieval_time_seconds", "preprocessing_time_seconds",
    "inference_time_seconds", "source_span_seconds", "unique_frame_count",
    "left_padding_count", "right_padding_count",
])


def _cell_by_tag(doc, tag):
    for cell in doc.cells:
        if tag in cell.metadata.get("tags", []):
            return cell
    raise AssertionError(f"notebook has no cell tagged {tag!r}")


def _assert_saved_source_is_clean():
    doc = nbformat.read(NOTEBOOK_PATH, as_version=4)
    for cell in doc.cells:
        if cell.cell_type == "code":
            assert cell.execution_count is None, (
                "saved notebook code cell carries an execution count")
            assert cell.outputs == [], (
                "saved notebook code cell carries stored outputs")
    return doc


def _config_source(db_path, detection_ids, reference_labels, seed=None):
    return (
        f"DB_PATH = {str(db_path)!r}\n"
        f"DETECTION_IDS = {detection_ids!r}\n"
        f"SEED = {seed!r}\n"
        f"ACTIVITIES = {ACTIVITIES!r}\n"
        "DESCRIPTIONS = None\n"
        "DEVICE = 'auto'\n"
        "MODEL_PATH = None\n"
        "CACHE_DIR = None\n"
        f"REFERENCE_LABELS = {reference_labels!r}\n"
        "MAX_VIDEO_SECONDS = 120.0\n"
        "TOP_K = 3\n"
    )


def _patch_source(fail_detection=None, fail_interval=10.0):
    text = """
import math as _math
import socket as _socket

def _blocked_network(*args, **kwargs):
    raise RuntimeError("network access is disabled in the synthetic notebook test")

_socket.create_connection = _blocked_network
_socket.socket = _blocked_network

import activity_classification as _activity_classification
from activity_classification import ActivityPrediction as _ActivityPrediction
from activity_classification import ClassificationResult as _ClassificationResult

FAKE_TOP_LABEL = {top_label!r}

class _FakeXCLIPClassifier:
    def __init__(self, device="auto", model_path=None, cache_dir=None):
        self.model = "fake-xclip-base"
        self.model_revision = "fake-revision-0001"
        self.device = "cpu (fake)"
        self.dtype = "float32"
        self.num_frames = 32

    def classify(
        self,
        frames,
        activities,
        *,
        prompt_template="A video of people {{activity}}.",
        descriptions=None,
    ):
        count = int(frames.shape[0]) if hasattr(frames, "shape") else len(frames)
        ranked = [FAKE_TOP_LABEL] + [
            activity for activity in activities if activity != FAKE_TOP_LABEL]
        logits = [4.0 - 0.25 * index for index in range(len(ranked))]
        peak = _math.exp(max(logits))
        weights = [_math.exp(value - peak) for value in logits]
        total = sum(weights)
        predictions = tuple(
            _ActivityPrediction(
                label=label,
                prompt=prompt_template.format(activity=label),
                logit=logit,
                score=weights[index] / total,
            )
            for index, (label, logit) in enumerate(zip(ranked, logits))
        )
        return _ClassificationResult(
            predictions=predictions,
            model=self.model,
            model_revision=self.model_revision,
            device=self.device,
            dtype=self.dtype,
            input_frame_count=count,
            num_frames=32,
            selected_frame_indices=tuple(range(32)),
            score_type="candidate_relative_softmax",
            preprocessing_time_seconds=0.001 + 0.0001 * count,
            inference_time_seconds=0.002 + 0.0002 * count,
            total_time_seconds=0.004 + 0.0003 * count,
            peak_gpu_memory_allocated_mib=None,
            peak_gpu_memory_reserved_mib=None,
        )

_activity_classification.XCLIPClassifier = _FakeXCLIPClassifier
""".format(top_label=TOP_LABEL)
    if fail_detection is not None:
        text += "\nimport video_retrieval as _video_retrieval\n"
        text += (
            "\nclass _FailingRetriever(_video_retrieval.VideoRetriever):\n"
            "    def get_temporal_clip(self, detection_id, *, interval_seconds,"
            " sample_count=32):\n"
            f"        if interval_seconds == {fail_interval!r} and"
            f" detection_id == {fail_detection!r}:\n"
            '            raise RuntimeError("synthetic temporal retrieval failure")\n'
            "        return super().get_temporal_clip(\n"
            "            detection_id,\n"
            "            interval_seconds=interval_seconds,\n"
            "            sample_count=sample_count,\n"
            "        )\n"
            "\n_video_retrieval.VideoRetriever = _FailingRetriever\n"
        )
    return text


def _payload(doc):
    last = doc.cells[-1]
    for output in last.outputs:
        for line in str(output.get("text", "")).splitlines():
            if line.startswith(RESULT_JSON_PREFIX):
                return json.loads(line[len(RESULT_JSON_PREFIX):])
    raise AssertionError(
        f"expected RESULT_JSON payload in the appended cell; got"
        f" {last.outputs!r}")


def _assert_payload_keys(payload):
    for summary in payload["summary"]:
        assert set(summary) == set(SUMMARY_KEYS)


def _db_state(db_path):
    size = Path(db_path).stat().st_size
    with closing(connect_database(db_path, read_only=True)) as connection:
        counts = table_counts(connection)
    return {"bytes": size, "counts": counts}


def _detection_id_at_frame(db_path, frame_number):
    with closing(connect_database(db_path, read_only=True)) as connection:
        rows = connection.execute(
            "SELECT d.detection_id FROM FaceDetection AS d"
            " JOIN Frame AS f ON f.frame_id = d.frame_id"
            " WHERE f.frame_number = ?", (frame_number,)).fetchall()
    assert rows, f"no detection at frame {frame_number} in {db_path}"
    return rows[0][0]


def _eligible_detection_ids(db_path):
    from analysis_db.paths import REPOSITORY_ROOT

    with closing(connect_database(db_path, read_only=True)) as connection:
        rows = connection.execute(
            "SELECT d.detection_id, v.file_path FROM Video AS v"
            " JOIN Frame AS f ON f.video_id = v.video_id"
            " JOIN FaceDetection AS d ON d.frame_id = f.frame_id"
            " WHERE v.duration_seconds IS NOT NULL"
            " AND v.duration_seconds > 0 AND v.duration_seconds <= 120"
            " ORDER BY v.video_id, d.detection_id").fetchall()
    return [row[0] for row in rows
            if row[1] is not None
            and (REPOSITORY_ROOT / str(row[1])).resolve().is_file()]


def _insert_before_imports(doc, patch_source):
    imports_cell = _cell_by_tag(doc, "imports")
    doc.cells.insert(
        doc.cells.index(imports_cell), nbformat.v4.new_code_cell(patch_source))


def _append_cell(doc, source):
    doc.cells.append(nbformat.v4.new_code_cell(source))


def _executable_within(prefix, executable_text):
    executable = Path(executable_text)
    candidate = str(executable.absolute())
    if candidate == prefix or candidate.startswith(prefix + os.sep):
        return True
    try:
        candidate = str(executable.resolve())
    except OSError:
        return False
    return candidate == prefix or candidate.startswith(prefix + os.sep)


def _venv_kernelspec():
    prefix = str(Path(sys.prefix).resolve())
    manager = KernelSpecManager()

    def matching(name):
        try:
            spec = manager.get_kernel_spec(name)
        except Exception:
            return None
        argv = getattr(spec, "argv", []) or []
        for candidate in argv[:1]:
            if _executable_within(prefix, candidate):
                return name
        return None

    for name in manager.find_kernel_specs():
        resolved = matching(name)
        if resolved is not None:
            return resolved
    if util.find_spec("ipykernel") is None:
        raise RuntimeError(
            "no Jupyter kernel resolved to the backend venv"
            f" ({prefix}) and ipykernel is not installed in it; run"
            " `uv run --locked python -m ipykernel install --sys-prefix`"
            " inside backend/ and retry")
    subprocess.run(
        [sys.executable, "-m", "ipykernel", "install", "--sys-prefix"],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    manager = KernelSpecManager()
    for name in manager.find_kernel_specs():
        resolved = matching(name)
        if resolved is not None:
            return resolved
    raise RuntimeError(
        "no Jupyter kernel resolves to the backend venv"
        f" ({prefix}); run"
        " `uv run --locked python -m ipykernel install --sys-prefix`"
        " inside backend/ and retry")


def _execute(doc):
    client = NotebookClient(
        doc,
        timeout=900,
        allow_errors=False,
        kernel_name=_venv_kernelspec(),
        resources={"metadata": {"path": str(BACKEND)}})
    client.execute()
    return doc


def _run_success_scenario(db_path):
    doc = _assert_saved_source_is_clean()
    before = _db_state(db_path)
    detection_id = _detection_id_at_frame(db_path, 24)
    _cell_by_tag(doc, "configuration").source = _config_source(
        db_path, [detection_id], {detection_id: TOP_LABEL})
    _insert_before_imports(doc, _patch_source())
    success_assertions = (
        f"""
ROW_KEYS = {ROW_KEYS!r}
SUMMARY_KEYS = {SUMMARY_KEYS!r}
SAMPLING_KEYS = {sorted(SAMPLING_KEYS)!r}

assert len(comparison_rows) == 4
assert set(row["condition"] for row in comparison_rows) == {{
    "consecutive_32", "uniform_5s", "uniform_10s", "uniform_15s"}}
assert all(row["num_frames"] == 32 for row in comparison_rows)
assert all(row["reference_label"] == "Dancing" for row in comparison_rows)
assert all(row["top1_correct"] is True for row in comparison_rows)
assert all(row["top3_correct"] is True for row in comparison_rows)
assert all(row["detection_id"] == {detection_id!r} for row in comparison_rows)
assert all(row["reference_rank"] == 1 for row in comparison_rows)
assert all(row["reference_score"] > 0 for row in comparison_rows)
assert all(row["unique_frame_count"] >= 1 for row in comparison_rows)
assert all(row["left_padding_count"] >= 0 for row in comparison_rows)
assert all(row["right_padding_count"] >= 0 for row in comparison_rows)
assert all(type(row["source_span_seconds"]) is float for row in comparison_rows)
assert all(len(row["predictions"]) == 9 for row in comparison_rows)
assert all("label" in prediction and "score" in prediction
           for row in comparison_rows for prediction in row["predictions"])
assert all(set(row) == set(ROW_KEYS) for row in comparison_rows)
assert set(SAMPLING_KEYS) <= set(comparison_rows[0])
assert "Per-row comparison (quality and labels)" in results_table_markdown
assert "Per-row comparison (sampling and timing)" in results_table_markdown
for header in ("num_frames", "span (s)", "unique", "pad L/R"):
    assert header in results_table_markdown
assert experiment_errors == {{
    "consecutive_32": [], "uniform_5s": [], "uniform_10s": [], "uniform_15s": []}}
assert len(quality_summary) == 4
assert all(summary["evaluated_detections"] == 1 for summary in quality_summary)
assert all(summary["top1_accuracy"] == 1.0 for summary in quality_summary)
assert all(summary["top3_accuracy"] == 1.0 for summary in quality_summary)
assert all(set(summary) == set(SUMMARY_KEYS) for summary in quality_summary)
assert all(summary["excluded"]["unlabeled"] == [] for summary in quality_summary)
assert all(summary["excluded"]["failed_in_this_condition"] == []
           for summary in quality_summary)
assert all(summary["excluded"]["failed_in_other_conditions"] == []
           for summary in quality_summary)
import json as _json
print({RESULT_JSON_PREFIX!r} + _json.dumps({{
    "row_keys": sorted(comparison_rows[0]),
    "rows": [
        {{
            "condition": row["condition"],
            "detection_id": row["detection_id"],
            "num_frames": row["num_frames"],
            "reference_label": row["reference_label"],
            "top1_correct": row["top1_correct"],
            "top3_correct": row["top3_correct"],
            "retrieval_time_seconds": row["retrieval_time_seconds"],
            "preprocessing_time_seconds": row["preprocessing_time_seconds"],
            "inference_time_seconds": row["inference_time_seconds"],
            "source_span_seconds": row["source_span_seconds"],
            "unique_frame_count": row["unique_frame_count"],
            "left_padding_count": row["left_padding_count"],
            "right_padding_count": row["right_padding_count"],
        }}
        for row in comparison_rows],
    "summary": [dict(summary) for summary in quality_summary],
}}))
""")
    _append_cell(doc, success_assertions)
    _execute(doc)
    after = _db_state(db_path)
    assert before == after, "database changed during notebook execution"

    payload = _payload(doc)
    _assert_payload_keys(payload)
    assert len(payload["rows"]) == 4
    for sampling_row in payload["rows"]:
        for key in SAMPLING_KEYS:
            assert key in sampling_row, (
                f"payload row lacks sampling column {key!r}: {sampling_row!r}")
        assert sampling_row["num_frames"] == 32
        assert type(sampling_row["source_span_seconds"]) is float
        assert sampling_row["retrieval_time_seconds"] >= 0.0
        assert sampling_row["preprocessing_time_seconds"] >= 0.0
        assert sampling_row["inference_time_seconds"] >= 0.0
        assert sampling_row["unique_frame_count"] >= 1
        assert sampling_row["left_padding_count"] >= 0
        assert sampling_row["right_padding_count"] >= 0
    assert all(row["reference_label"] == TOP_LABEL for row in payload["rows"])
    assert all(row["top1_correct"] is True for row in payload["rows"])
    assert all(row["top3_correct"] is True for row in payload["rows"])
    return payload


def _run_failure_path_scenario(db_path):
    doc = _assert_saved_source_is_clean()
    before = _db_state(db_path)
    failed = _detection_id_at_frame(db_path, 24)
    acceptable = _detection_id_at_frame(db_path, 47)
    unlabeled = _detection_id_at_frame(db_path, 0)
    _cell_by_tag(doc, "configuration").source = _config_source(
        db_path,
        [failed, acceptable, unlabeled],
        {failed: TOP_LABEL, acceptable: TOP_LABEL},
    )
    _insert_before_imports(doc, _patch_source(fail_detection=failed))
    failure_assertions = (
        f"""
ROW_KEYS = {ROW_KEYS!r}
SUMMARY_KEYS = {SUMMARY_KEYS!r}

assert set(row["condition"] for row in comparison_rows) == {{
    "consecutive_32", "uniform_5s", "uniform_10s", "uniform_15s"}}
assert len(comparison_rows) == 11
assert not [
    row for row in comparison_rows
    if row["detection_id"] == {failed!r} and row["condition"] == "uniform_10s"]
assert experiment_errors["uniform_10s"] == [
    {{"detection_id": {failed!r}, "step": "retrieval", "error": "RuntimeError"}}]
assert all(records == [] for name, records in experiment_errors.items()
           if name != "uniform_10s")
assert all(row["detection_id"] in ({failed!r}, {acceptable!r}, {unlabeled!r})
           for row in comparison_rows)
unlabeled_row = [row for row in comparison_rows
                 if row["detection_id"] == {unlabeled!r}
                 and row["condition"] == "uniform_5s"]
assert len(unlabeled_row) == 1
assert unlabeled_row[0]["reference_label"] is None
assert unlabeled_row[0]["reference_rank"] is None
assert unlabeled_row[0]["reference_score"] is None
assert unlabeled_row[0]["top1_correct"] is None
assert unlabeled_row[0]["top3_correct"] is None
assert len(quality_summary) == 4
for summary in quality_summary:
    assert summary["evaluated_detections"] == 1
    assert summary["top1_accuracy"] == 1.0
    assert summary["top3_accuracy"] == 1.0
    excluded = summary["excluded"]
    assert {unlabeled!r} in excluded["unlabeled"]
    if summary["condition"] == "uniform_10s":
        assert {failed!r} in excluded["failed_in_this_condition"]
        assert {failed!r} not in excluded["failed_in_other_conditions"]
    else:
        assert {failed!r} in excluded["failed_in_other_conditions"]
        assert {failed!r} not in excluded["failed_in_this_condition"]
assert all(set(row) == set(ROW_KEYS) for row in comparison_rows)
assert all(set(summary) == set(SUMMARY_KEYS) for summary in quality_summary)
import json as _json
print({RESULT_JSON_PREFIX!r} + _json.dumps({{
    "row_keys": sorted(comparison_rows[0]),
    "rows": [
        {{
            "condition": row["condition"],
            "detection_id": row["detection_id"],
            "top1_correct": row["top1_correct"],
            "reference_label": row["reference_label"],
        }}
        for row in comparison_rows],
    "summary": [dict(summary) for summary in quality_summary],
}}))
""")
    _append_cell(doc, failure_assertions)
    _execute(doc)
    after = _db_state(db_path)
    assert before == after, "database changed during notebook execution"

    payload = _payload(doc)
    _assert_payload_keys(payload)
    assert len(payload["rows"]) == 11
    failed_rows = [
        row for row in payload["rows"]
        if row["detection_id"] == failed and row["condition"] == "uniform_10s"]
    assert failed_rows == []
    unlabeled_rows = [
        row for row in payload["rows"] if row["detection_id"] == unlabeled]
    assert all(row["reference_label"] is None for row in unlabeled_rows)
    assert all(row["top1_correct"] is None for row in unlabeled_rows)
    return payload


def _run_invalid_reference_scenario(db_path):
    doc = _assert_saved_source_is_clean()
    before = _db_state(db_path)
    detection_id = _detection_id_at_frame(db_path, 24)
    _cell_by_tag(doc, "configuration").source = _config_source(
        db_path, [detection_id], {detection_id: "Hacking"})
    _insert_before_imports(doc, _patch_source())
    client = NotebookClient(
        doc,
        timeout=900,
        allow_errors=False,
        kernel_name=_venv_kernelspec(),
        resources={"metadata": {"path": str(BACKEND)}})
    with pytest.raises(CellExecutionError, match="Hacking"):
        client.execute()
    after = _db_state(db_path)
    assert before == after, "database changed during notebook execution"


def _run_auto_selection_scenario(db_path, seed):
    doc = _assert_saved_source_is_clean()
    before = _db_state(db_path)
    _cell_by_tag(doc, "configuration").source = _config_source(
        db_path, None, {}, seed=seed)
    _insert_before_imports(doc, _patch_source())
    auto_assertions = (
        f"""
assert set(row["condition"] for row in comparison_rows) == {{
    "consecutive_32", "uniform_5s", "uniform_10s", "uniform_15s"}}
assert len(comparison_rows) == 4
auto_detection_id = comparison_rows[0]["detection_id"]
assert all(row["detection_id"] == auto_detection_id
           for row in comparison_rows)
assert all(row["num_frames"] == 32 for row in comparison_rows)
assert all(row["predictions"] and row["predictions"][0]["label"]
           == FAKE_TOP_LABEL for row in comparison_rows)
assert experiment_errors == {{
    "consecutive_32": [], "uniform_5s": [], "uniform_10s": [],
    "uniform_15s": []}}
import json as _json
print({RESULT_JSON_PREFIX!r} + _json.dumps(
    {{"detection_id": auto_detection_id}}))
""")
    _append_cell(doc, auto_assertions)
    _execute(doc)
    after = _db_state(db_path)
    assert before == after, "database changed during notebook execution"
    payload = _payload(doc)
    eligible = _eligible_detection_ids(db_path)
    assert payload["detection_id"] in eligible
    expected = list(eligible)
    _random.Random(seed).shuffle(expected)
    assert payload["detection_id"] == expected[0], (
        f"auto-selection picked {payload['detection_id']} for seed {seed},"
        f" expected {expected[0]}")
    return payload["detection_id"]


def test_notebook_auto_selection_uses_seed(video):
    from contextlib import closing as _closing
    import sqlite3 as _sqlite3

    with _closing(_sqlite3.connect(video.db_path)) as _connection:
        _connection.execute("UPDATE Video SET duration_seconds = 2.0")
        _connection.commit()
    _run_auto_selection_scenario(video.db_path, 1)


def test_synthetic_notebook_execution_passes_all_conditions(video):
    _run_success_scenario(video.db_path)


def test_notebook_failure_path_and_missing_reference(video):
    _run_failure_path_scenario(video.db_path)


def test_notebook_invalid_reference_label_raises(video):
    _run_invalid_reference_scenario(video.db_path)


def test_saved_notebook_source_is_free_of_outputs():
    _assert_saved_source_is_clean()
