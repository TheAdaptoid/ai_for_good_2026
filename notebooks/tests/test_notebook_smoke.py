"""Execute notebook copies in memory with the uv interpreter and temporary data."""

import json
import os
from pathlib import Path
import shutil
import sys

import nbformat
from nbclient import NotebookClient
from jupyter_client import KernelManager
import pytest


pytestmark = [
    pytest.mark.model_smoke,
    pytest.mark.skipif(
        os.environ.get("RUN_XCLIP_SMOKE") != "1",
        reason="Set RUN_XCLIP_SMOKE=1 for in-memory notebook acceptance",
    ),
]
PROJECT_DIR = Path(__file__).resolve().parents[1]
NOTEBOOK = PROJECT_DIR / "activity_recognition.ipynb"
REVISION = "6746d6a5202bf24300cd9bf36f457f174483d41b"


def tagged_cell(notebook, tag):
    cells = [cell for cell in notebook.cells if tag in cell.metadata.get("tags", [])]
    assert len(cells) == 1, f"Expected one cell tagged {tag}"
    return cells[0]


def execute_in_memory(notebook):
    original = NOTEBOOK.read_bytes()
    km = KernelManager(kernel_name="python3")
    km.kernel_spec.argv = [
        sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}",
    ]
    try:
        return NotebookClient(
            notebook, km=km, timeout=600,
            resources={"metadata": {"path": str(PROJECT_DIR)}},
        ).execute()
    finally:
        if km.has_kernel:
            km.shutdown_kernel(now=True)
        assert NOTEBOOK.read_bytes() == original
        saved = nbformat.read(NOTEBOOK, as_version=4)
        for cell in saved.cells:
            if cell.cell_type == "code":
                assert cell.outputs == []
                assert cell.execution_count is None


def test_default_empty_notebook_does_not_load_weights(tmp_path):
    output_dir = tmp_path / "results"
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    tagged_cell(notebook, "input-configuration").source += "\n" + f"""
assert VIDEO_PATHS == []
assert EXPORT_RESULTS is False
assert OUTPUT_DIR == Path('results')
OUTPUT_DIR = Path({str(output_dir)!r})
assert not OUTPUT_DIR.exists()
import sys
assert sys.executable == {sys.executable!r}
def forbidden_model_or_video(*args, **kwargs):
    raise AssertionError('Empty notebook attempted model loading or video sampling')
get_recognizer = sample_video = forbidden_model_or_video
"""
    tagged_cell(notebook, "result-export").source += "\n" + """
assert recognizer is None and model_load_time_seconds is None
assert single_result is None and records == []
assert results_df.empty and errors_df.empty
assert not OUTPUT_DIR.exists()
"""
    executed = execute_in_memory(notebook)
    assert not any(
        output.output_type == "error"
        for cell in executed.cells if cell.cell_type == "code" for output in cell.outputs
    )


@pytest.mark.parametrize("export_results", [False, True])
def test_configured_notebook_plots_and_opt_in_exports(export_results, tmp_path, make_video):
    import activity_recognition  # Offline configuration before ML imports.
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    video = make_video()
    paths = [str(video)]
    if export_results:
        paths.append(str(tmp_path / "missing.avi"))
    output_dir = tmp_path / "results"
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    tagged_cell(notebook, "input-configuration").source += "\n" + f"""
VIDEO_PATHS = {paths!r}
ACTIVITIES = ['Dancing', 'Walking']
DEVICE = {device!r}
REPEATS = 1
EXPORT_RESULTS = {export_results!r}
OUTPUT_DIR = Path({str(output_dir)!r})
import os
import sys
import torch
torch.set_num_threads(4)
assert sys.executable == {sys.executable!r}
assert Path.cwd() == Path({str(PROJECT_DIR)!r})
assert os.environ['HF_HUB_OFFLINE'] == os.environ['TRANSFORMERS_OFFLINE'] == '1'
"""
    tagged_cell(notebook, "experiment-configuration").source += "\n" + """
EXPERIMENTS = [{
    'name': 'smoke', 'activities': ACTIVITIES,
    'prompt_template': '{activity}', 'descriptions': None,
}]
"""
    tagged_cell(notebook, "result-export").source += "\n" + f"""
assert len(records) == len(results_df) == 1
assert len(errors_df) == {int(export_results)}
assert single_result is not None
assert single_result['device'] == DEVICE
assert records[0]['device'] == DEVICE
assert records[0]['dtype'] == ('torch.float16' if DEVICE == 'cuda' else 'torch.float32')
assert records[0]['model_revision'] == {REVISION!r}
assert records[0]['num_frames'] == single_result['num_frames'] == 32
assert results_df.iloc[0]['num_frames'] == 32
assert records[0]['prompts'] == {{'dancing': 'Dancing', 'walking': 'Walking'}}
assert records[0]['prompt_strategy'] == 'raw_labels'
assert records[0]['activity'] == max(records[0]['scores'], key=records[0]['scores'].get)
assert abs(sum(records[0]['scores'].values()) - 1) < 1e-6
assert 0 < records[0]['inference_time_seconds'] <= records[0]['total_time_seconds']
json.dumps(records, allow_nan=False)
for key in ('inference_time_seconds', 'total_time_seconds', 'preprocessing_time_seconds'):
    assert results_df.iloc[0][key] == records[0][key]
for key, score in records[0]['scores'].items():
    assert results_df.iloc[0]['scores.' + key] == score
display({{'application/json': {{'smoke_records': records}}}}, raw=True)
"""
    try:
        executed = execute_in_memory(notebook)
        outputs = [
            output for cell in executed.cells if cell.cell_type == "code"
            for output in cell.outputs
        ]
        assert not any(output.output_type == "error" for output in outputs)
        assert any("image/png" in output.get("data", {}) for output in outputs)
        assert not any(
            "Single-clip preview/classification failed" in output.get("text", "")
            for output in outputs
        )
        payloads = [
            output["data"]["application/json"] for output in outputs
            if "application/json" in output.get("data", {})
            and "smoke_records" in output["data"]["application/json"]
        ]
        assert len(payloads) == 1
        records = payloads[0]["smoke_records"]
        assert len(records) == 1
        if not export_results:
            assert not output_dir.exists()
        else:
            import pandas as pd

            assert {path.name for path in output_dir.iterdir()} == {
                "activity_results.json", "activity_results.csv", "activity_errors.csv",
            }
            exported = json.loads((output_dir / "activity_results.json").read_text())
            assert exported == records
            results = pd.read_csv(output_dir / "activity_results.csv")
            errors = pd.read_csv(output_dir / "activity_errors.csv")
            assert len(results) == len(errors) == 1
            assert results.iloc[0]["video_id"] == video.stem
            assert errors.iloc[0]["video_id"] == "missing"
            assert errors.iloc[0]["error_type"] == "FileNotFoundError"
            assert errors.iloc[0]["stage"] == "warmup"
            assert all(record["video_id"] != "missing" for record in exported)
            for key, score in records[0]["scores"].items():
                assert results.iloc[0][f"scores.{key}"] == pytest.approx(score)
            for key in (
                "preprocessing_time_seconds", "inference_time_seconds", "total_time_seconds",
            ):
                assert results.iloc[0][key] == pytest.approx(records[0][key])
    finally:
        video.unlink(missing_ok=True)
        if output_dir.is_dir():
            shutil.rmtree(output_dir)
