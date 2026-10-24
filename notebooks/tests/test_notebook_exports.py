"""Exercise the notebook's tagged export cell with temporary result tables."""

import json
from pathlib import Path

import nbformat
import pandas as pd


NOTEBOOK = Path(__file__).resolve().parents[1] / "activity_recognition.ipynb"


def test_error_free_export_replaces_previous_errors(tmp_path):
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    cells = [
        cell for cell in notebook.cells
        if "result-export" in cell.metadata.get("tags", [])
    ]
    assert len(cells) == 1
    export_cell = compile(cells[0].source, str(NOTEBOOK), "exec")
    error_columns = [
        "video_id", "experiment", "stage", "repeat_index", "error_type", "message",
    ]
    errors = pd.DataFrame([{
        "video_id": "missing", "experiment": "baseline", "stage": "warmup",
        "repeat_index": None, "error_type": "FileNotFoundError",
        "message": "old failure",
    }], columns=error_columns)
    namespace = {"EXPORT_RESULTS": True, "OUTPUT_DIR": tmp_path, "json": json}

    for video_id, errors_df in (
        ("previous", errors), ("current", pd.DataFrame(columns=error_columns)),
    ):
        records = [{"video_id": video_id, "activity": "walking", "scores": {"walking": 1.0}}]
        namespace.update(
            records=records, results_df=pd.json_normalize(records), errors_df=errors_df,
        )
        exec(export_cell, namespace)

        assert json.loads((tmp_path / "activity_results.json").read_text()) == records
        results = pd.read_csv(tmp_path / "activity_results.csv")
        assert results.to_dict("records") == [{
            "video_id": video_id, "activity": "walking", "scores.walking": 1.0,
        }]
        exported_errors = pd.read_csv(tmp_path / "activity_errors.csv")
        assert list(exported_errors.columns) == error_columns
        if video_id == "previous":
            assert exported_errors["message"].tolist() == ["old failure"]
        else:
            assert exported_errors.empty
            assert "old failure" not in (tmp_path / "activity_errors.csv").read_text()
