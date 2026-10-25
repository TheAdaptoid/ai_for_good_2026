"""Spec 005 stages on synthetic signals. No model, no real footage: the activity stage runs with a
fake classifier and a fake decoder; the decoder test uses a generated pattern video."""

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from analysis_db.paths import DEFAULT_DB
from analysis_db.pipeline_import import parse_import_file
from analysis_db.storage import initialize_database
from pipeline.contracts import ClipProposal, DetectionSignal, ExpressionScores, VideoSignals
from pipeline.frames import read_windows
from pipeline.local_analysis import (
    PRIORITY_METHOD, ExpressionAffectAnnotator, GenerationConfig, ParticipantPositivePriority,
    PresenceSegmenter, ZeroShotActivityAnnotator, affect_label, aggregate_activity,
    participant_positive_priority, window_indices,
)
from tests.conftest import encode_video, patterned_frames

BACKEND = Path(__file__).resolve().parents[1]
GENERATE = BACKEND / "scripts" / "generate_pipeline_output.py"
IMPORT = BACKEND / "scripts" / "import_pipeline_output.py"
FPS = 10.0  # gap 2 s = 20 frames, presence 1 s = 10, min clip 5 s = 50, max clip 60 s = 600
POS, NEU, NEG = (0.8, 0.1, 0.1), (0.1, 0.8, 0.1), (0.1, 0.1, 0.8)


def video(rows, frame_count=10_000, fps=FPS):
    """rows: (person, frame, scores or None)."""
    detections = tuple(
        DetectionSignal(i, person, frame, frame / fps,
                        None if scores is None else ExpressionScores(*scores), None)
        for i, (person, frame, scores) in enumerate(sorted(rows, key=lambda r: (r[1], r[0]))))
    return VideoSignals(1, "v.mp4", fps, frame_count, detections)


def present(person, start, end, step=2, scores=POS):
    return [(person, f, scores) for f in range(start, end + 1, step)]


def clips_of(rows, **kwargs):
    return [(c.start_frame, c.end_frame, c.person_ids)
            for c in PresenceSegmenter().segment(video(rows, **kwargs))]


# --- Segmentation --------------------------------------------------------------------------

def test_one_participant_throughout_is_split_only_at_max_length():
    assert clips_of(present("A", 0, 1000)) == [(0, 499, ("A",)), (500, 1000, ("A",))]


def test_participant_entering_starts_a_clip():
    assert clips_of(present("A", 0, 300) + present("B", 100, 300)) == [
        (0, 99, ("A",)), (100, 300, ("A", "B"))]


def test_participant_leaving_starts_a_clip():
    assert clips_of(present("A", 0, 300) + present("B", 0, 150)) == [
        (0, 150, ("A", "B")), (151, 300, ("A",))]


def test_set_change_between_people():
    assert clips_of(present("A", 0, 200) + present("B", 140, 400)) == [
        (0, 139, ("A",)), (140, 200, ("A", "B")), (201, 400, ("B",))]


def test_short_gap_keeps_presence_continuous():
    assert clips_of(present("A", 0, 100) + present("A", 115, 300)) == [(0, 299, ("A",))]


def test_long_gap_with_nobody_has_no_clip():
    assert clips_of(present("A", 0, 100) + present("A", 400, 600)) == [
        (0, 100, ("A",)), (400, 600, ("A",))]


def test_multiple_participants_together():
    assert clips_of(present("A", 0, 300) + present("B", 0, 300) + present("C", 0, 300)) == [
        (0, 300, ("A", "B", "C"))]


def test_detection_flicker_below_minimum_presence_is_ignored():
    rows = present("A", 0, 300) + [("B", 150, POS), ("B", 152, POS)]
    assert clips_of(rows) == [(0, 300, ("A",))]


def test_rapid_set_change_merges_into_previous_clip_with_union():
    # B is present 3 s (above minimum presence, below the 5 s minimum clip).
    assert clips_of(present("A", 0, 300) + present("B", 100, 130)) == [
        (0, 130, ("A", "B")), (131, 300, ("A",))]


def test_no_detections_no_clips():
    assert clips_of([]) == []


def test_clips_are_clamped_to_the_video():
    assert clips_of(present("A", 0, 100), frame_count=90) == [(0, 89, ("A",))]


def test_segmentation_is_deterministic():
    rows = present("A", 0, 900) + present("B", 120, 700, step=3) + present("C", 50, 60)
    assert clips_of(rows) == clips_of(list(reversed(rows)))


# --- Visible affect ------------------------------------------------------------------------

def scores(*triples):
    return [ExpressionScores(*t) for t in triples]


@pytest.mark.parametrize("triples, expected", [
    ([POS, POS], ("Visible Positive Affect", 0.8)),
    ([NEU], ("Visible Neutral Affect", 0.8)),
    ([NEG, NEG, NEU], ("Visible Negative Affect", 0.5666666666666667)),
])
def test_affect_label_takes_highest_mean(triples, expected):
    label, value = affect_label(scores(*triples))
    assert label == expected[0] and value == pytest.approx(expected[1])


def test_affect_ties_prefer_neutral_then_positive():
    assert affect_label(scores((0.4, 0.4, 0.2)))[0] == "Visible Neutral Affect"
    assert affect_label(scores((0.45, 0.1, 0.45)))[0] == "Visible Positive Affect"
    assert affect_label([]) is None


def test_affect_annotations_per_participant_from_own_detections():
    rows = (present("A", 0, 300, scores=POS) + present("B", 0, 300, scores=NEG)
            + present("C", 0, 300, scores=None))  # C has detections but no scores
    signals = video(rows)
    clips = PresenceSegmenter().segment(signals)
    out = ExpressionAffectAnnotator().annotate(signals, clips)
    assert [(a.person_id, a.label_name, a.confidence) for a in out] == [
        ("A", "Visible Positive Affect", 0.8), ("B", "Visible Negative Affect", 0.8)]
    assert all((a.start_frame, a.end_frame, a.clip_index) == (0, 300, 0) for a in out)


def test_single_detection_and_member_without_detections_in_clip():
    signals = video([("A", 5, NEU)])
    clip = ClipProposal(0, 10, ("A", "B"))
    out = ExpressionAffectAnnotator().annotate(signals, [clip])
    assert [(a.person_id, a.label_name) for a in out] == [("A", "Visible Neutral Affect")]


# --- Review priority -----------------------------------------------------------------------

def test_priority_formula_is_exact():
    assert participant_positive_priority([0.8, 0.2], 2) == pytest.approx(1.1 ** 2 * 0.5)
    assert participant_positive_priority([0.6], 1) == pytest.approx(0.66)
    assert participant_positive_priority([0.0, 0.0], 2) == 0.0
    assert participant_positive_priority([], 3) is None


def test_priority_averages_per_participant_not_per_detection():
    # A: 10 detections at 0.8; B: 1 detection at 0.2. Per detection would give ~0.745 x 1.21.
    rows = [("A", f, (0.8, 0.1, 0.1)) for f in range(0, 20, 2)] + [("B", 4, (0.2, 0.7, 0.1))]
    score = ParticipantPositivePriority().score(video(rows), ClipProposal(0, 20, ("A", "B")), [])
    assert score == pytest.approx(1.1 ** 2 * (0.8 + 0.2) / 2)
    assert ParticipantPositivePriority.method == PRIORITY_METHOD == "participant_count_positive_affect_v1"


def test_priority_counts_every_member_in_n_and_can_exceed_one():
    rows = [(p, 1, (0.95, 0.03, 0.02)) for p in "ABCDEFGHIJ"]
    score = ParticipantPositivePriority().score(video(rows), ClipProposal(0, 5, tuple("ABCDEFGHIJ")), [])
    assert score == pytest.approx(1.1 ** 10 * 0.95, rel=1e-6) and score > 1
    with_silent = ParticipantPositivePriority().score(video([("A", 1, POS)]), ClipProposal(0, 5, ("A", "Z")), [])
    assert with_silent == pytest.approx(1.1 ** 2 * 0.8)


def test_priority_none_without_scores_and_deterministic():
    scorer = ParticipantPositivePriority()
    assert scorer.score(video([("A", 1, None)]), ClipProposal(0, 5, ("A",)), []) is None
    rows = present("A", 0, 50, scores=(0.3, 0.6, 0.1))
    clip = ClipProposal(0, 50, ("A",))
    assert scorer.score(video(rows), clip, []) == scorer.score(video(rows), clip, [])


# --- Activity aggregation and stage ---------------------------------------------------------

LABELS = ["Singing", "Dancing", "Group Performance"]


def test_one_clear_label():
    windows = [{"Singing": 0.7, "Dancing": 0.2, "Group Performance": 0.1}] * 3
    assert aggregate_activity(windows, LABELS, 0.2, 0.3) == [("Singing", 0.7)]


def test_multi_label_when_two_labels_are_strongly_supported():
    windows = [{"Singing": 0.5, "Dancing": 0.05, "Group Performance": 0.45},
               {"Singing": 0.4, "Dancing": 0.1, "Group Performance": 0.5}]
    # One win each: the higher mean is representative; the other still clears the multi-label bar.
    assert aggregate_activity(windows, LABELS, 0.2, 0.3) == [("Group Performance", 0.475), ("Singing", 0.45)]


def test_unsupported_scores_emit_nothing():
    windows = [{"Singing": 0.34, "Dancing": 0.33, "Group Performance": 0.33}]
    assert aggregate_activity(windows, LABELS, 0.4, 0.5) == []
    assert aggregate_activity([], LABELS, 0.2, 0.3) == []


def test_most_common_label_wins_over_one_strong_window():
    windows = [{"Singing": 0.4, "Dancing": 0.35, "Group Performance": 0.25}] * 2 + [
        {"Singing": 0.0, "Dancing": 0.95, "Group Performance": 0.05}]
    result = aggregate_activity(windows, LABELS, 0.2, 0.9)
    assert result == [("Singing", pytest.approx(0.2667, abs=1e-4))]


def test_tie_in_wins_breaks_by_mean_then_label_order():
    windows = [{"Singing": 0.6, "Dancing": 0.4, "Group Performance": 0.0},
               {"Singing": 0.3, "Dancing": 0.7, "Group Performance": 0.0}]
    assert aggregate_activity(windows, LABELS, 0.2, 0.99)[0][0] == "Dancing"
    equal = [{"Singing": 0.5, "Dancing": 0.5, "Group Performance": 0.0}]
    assert aggregate_activity(equal, LABELS, 0.2, 0.99)[0][0] == "Singing"


def test_window_indices_are_deterministic_and_clamped():
    config = GenerationConfig()
    short = window_indices(ClipProposal(0, 9, ()), FPS, 100, 32, config)
    assert len(short) == 1 and min(short[0]) == 0 and len(short[0]) == 32
    long = window_indices(ClipProposal(0, 599, ()), FPS, 10_000, 32, config)
    assert len(long) == 4  # ceil(60 s / 15 s), capped at 4
    assert long == window_indices(ClipProposal(0, 599, ()), FPS, 10_000, 32, config)
    assert max(window_indices(ClipProposal(95, 100, ()), FPS, 100, 32, config)[0]) == 100


class FakeClassifier:
    num_frames = 4

    def __init__(self, by_window):
        self.by_window, self.calls, self.descriptions = by_window, [], None

    def classify(self, frames, activities, *, descriptions=None):
        self.descriptions = descriptions
        first = int(frames[0, 0, 0, 0])
        self.calls.append(first)
        scores = self.by_window(first)
        return SimpleNamespace(inference_time_seconds=0.01, predictions=[
            SimpleNamespace(label=l, score=scores[l]) for l in activities])


def fake_decoder(path, fps, windows):
    for window in windows:  # encodes the first frame index in the pixel value
        yield np.full((len(window), 2, 2, 3), window[0] % 256, dtype=np.uint8)


def test_activity_stage_emits_clip_level_annotations_with_prompts():
    classifier = FakeClassifier(lambda first: {"Singing": 0.6, "Dancing": 0.3, "Group Performance": 0.1}
                                if first < 50 else {"Singing": 0.1, "Dancing": 0.1, "Group Performance": 0.8})
    annotator = ZeroShotActivityAnnotator(classifier, LABELS, {"Singing": "people singing"},
                                          {"v.mp4": Path("v.mp4")}, fake_decoder)
    clips = [ClipProposal(0, 30, ("A",)), ClipProposal(200, 260, ("A",))]
    out = annotator.annotate(video([("A", 0, POS)]), clips)
    assert [(a.label_name, a.clip_index, a.person_id, a.confidence) for a in out] == [
        ("Singing", 0, None, 0.6), ("Dancing", 0, None, 0.3), ("Group Performance", 1, None, 0.8)]
    assert classifier.descriptions == {"Singing": "people singing",
                                       "Dancing": "A video of people dancing.",
                                       "Group Performance": "A video of people group performance."}
    assert annotator.windows_classified == 2


def test_missing_video_file_gives_no_activity():
    annotator = ZeroShotActivityAnnotator(FakeClassifier(lambda f: {}), LABELS, {}, {}, fake_decoder)
    assert annotator.annotate(video([("A", 0, POS)]), [ClipProposal(0, 10, ("A",))]) == []
    with pytest.raises(ValueError):
        ZeroShotActivityAnnotator(FakeClassifier(lambda f: {}), [], {}, {}, fake_decoder)


# --- Decoder ---------------------------------------------------------------------------------

def test_decoder_returns_exact_requested_frames(tmp_path):
    frames = patterned_frames(60)
    path = tmp_path / "pattern.mkv"
    encode_video(path, frames)  # lossless synthetic pattern, 24 fps
    windows = [[0, 1, 2], [30, 45, 59], [10, 10, 11]]
    got = list(read_windows(path, 24.0, windows))
    for window, array in zip(windows, got):
        assert array.shape == (len(window), 48, 64, 3)
        for k, index in enumerate(window):
            assert np.array_equal(array[k], frames[index])
    again = list(read_windows(path, 24.0, windows))
    assert all(np.array_equal(a, b) for a, b in zip(got, again))


# --- CLI ---------------------------------------------------------------------------------------

def synthetic_db(tmp_path) -> Path:
    db = tmp_path / "source.sqlite"
    initialize_database(db)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO Video (video_id, title, filename, file_path, duration_seconds, fps)"
                  " VALUES (1, 'one', 'one.mp4', 'data/videos/one.mp4', 100, 10)")
        c.executemany("INSERT INTO Person VALUES (?)", [("Person_0001",), ("Person_0002",)])
        detection = 0
        for person, start, end, s in (("Person_0001", 0, 300, POS), ("Person_0002", 100, 300, NEU)):
            for frame in range(start, end + 1, 2):
                detection += 1
                c.execute("INSERT OR IGNORE INTO Frame VALUES (?, 1, ?, ?)", (f"F{frame}", frame, frame / 10))
                c.execute("INSERT INTO FaceDetection (detection_id, person_id, frame_id, x1, y1, x2, y2,"
                          " det_score) VALUES (?, ?, ?, 0, 0, 1, 1, 0.9)", (detection, person, f"F{frame}"))
                c.execute("INSERT INTO Engagement (detection_id, positive_score, neutral_score,"
                          " negative_score) VALUES (?, ?, ?, ?)", (detection, *s))
    return db


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)


def test_cli_generates_an_importable_deterministic_file_without_writing_the_source(tmp_path):
    db = synthetic_db(tmp_path)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    out1, out2 = tmp_path / "a.json", tmp_path / "b.json"
    fixed = ["--no-activity", "--generated-at", "2026-10-25T00:00:00+00:00"]
    first = run(GENERATE, "--db", str(db), "--output", str(out1), *fixed)
    assert first.returncode == 0, first.stderr
    assert run(GENERATE, "--db", str(db), "--output", str(out2), *fixed).returncode == 0
    assert out1.read_bytes() == out2.read_bytes()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    parsed = parse_import_file(out1.read_text())
    assert parsed.pipeline.name == "tpa-local-analysis"
    assert parsed.pipeline.parameters["priority_method"] == PRIORITY_METHOD
    assert parsed.pipeline.parameters["gap_seconds"] == 2.0
    assert parsed.pipeline.parameters["activity"] == "disabled"
    clips = parsed.videos[0].clips
    assert [(c.start_frame, c.end_frame, c.participants) for c in clips] == [
        (0, 99, ("Person_0001",)), (100, 300, ("Person_0001", "Person_0002"))]
    assert clips[1].priority.score == pytest.approx(1.1 ** 2 * (0.8 + 0.1) / 2)
    labels = sorted((a.person_id, a.label.name) for a in parsed.videos[0].annotations)
    assert labels == [("Person_0001", "Visible Positive Affect"), ("Person_0001", "Visible Positive Affect"),
                      ("Person_0002", "Visible Neutral Affect")]
    working = tmp_path / "working.sqlite"
    shutil.copy(db, working)
    imported = run(IMPORT, "--input", str(out1), "--db", str(working))
    assert imported.returncode == 0 and "inserted: 3" in imported.stdout


def test_cli_requires_output_and_reports_unknown_video(tmp_path):
    db = synthetic_db(tmp_path)
    assert run(GENERATE, "--db", str(db)).returncode == 2
    bad = run(GENERATE, "--db", str(db), "--output", str(tmp_path / "x.json"), "--no-activity",
              "--video", "nope.mp4")
    assert bad.returncode == 1 and "unknown video" in bad.stderr and not (tmp_path / "x.json").exists()


@pytest.mark.parametrize("has_prompt", [False, True])
def test_custom_staff_labels_need_explicit_model_prompts(tmp_path, monkeypatch, has_prompt):
    from types import SimpleNamespace
    import activity_classification
    from scripts import generate_pipeline_output
    from scripts.generate_pipeline_output import main
    prompts = json.loads(generate_pipeline_output.PROMPTS_PATH.read_text())
    if has_prompt:
        prompts["Beatboxing"] = ["a person beatboxing"]
    prompt_file = tmp_path / "prompts.json"
    prompt_file.write_text(json.dumps(prompts))
    monkeypatch.setattr(generate_pipeline_output, "PROMPTS_PATH", prompt_file)
    db = synthetic_db(tmp_path)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO Label(name,category) VALUES('Beatboxing','activity')")
    monkeypatch.setattr(activity_classification, 'XCLIPClassifier',
                        lambda **kwargs: SimpleNamespace(num_frames=32))
    output = tmp_path / 'generated.json'
    assert main(['--db', str(db), '--output', str(output), '--device', 'cpu',
                 '--video-dir', str(tmp_path)]) == 0
    parsed = parse_import_file(output.read_text())
    labels = parsed.pipeline.parameters['activity_labels'].split(';')
    assert 'Singing' in labels
    assert ('Beatboxing' in labels) == has_prompt
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT is_active FROM Label WHERE name='Beatboxing'").fetchone() == (1,)


# --- Real model smoke test (skips without the model cache or the real database) --------------

MODEL_CACHE = BACKEND / ".cache" / "huggingface" / "hub" / "models--microsoft--xclip-base-patch16-zero-shot"


@pytest.mark.skipif(not (MODEL_CACHE.exists() and DEFAULT_DB.exists()),
                    reason="X-CLIP cache or real database not present")
def test_real_model_generates_a_valid_file_for_the_shortest_video(tmp_path):
    source = tmp_path / "copy.sqlite"
    shutil.copy(DEFAULT_DB, source)
    initialize_database(source)
    out = tmp_path / "real.json"
    result = run(GENERATE, "--db", str(source), "--output", str(out), "--video",
                 "this is me6-tik tok promo-singing.mp4", "--device", "cpu")
    assert result.returncode == 0, result.stderr
    parsed = parse_import_file(out.read_text())
    assert parsed.pipeline.models[0].name == "microsoft/xclip-base-patch16-zero-shot"
    assert parsed.videos and all(0 <= (a.confidence or 0) <= 1 for v in parsed.videos for a in v.annotations)
