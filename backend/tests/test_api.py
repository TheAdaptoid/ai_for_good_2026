import csv
import math
import io
import json
import shutil
import time
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from analysis_db import staff
from analysis_db.paths import DEFAULT_DB
from analysis_db.storage import connect_database, initialize_database
from api.app import create_app
from scripts.serve import build_parser as serve_parser

PASSWORD = "correct horse"
SINGING, SPOKEN, SUSTAINED, INACTIVE = 1, 4, 10, 6


@pytest.fixture
def videos_dir(tmp_path):
    directory = tmp_path / "videos"
    directory.mkdir()
    (directory / "one.mp4").write_bytes(bytes(range(256)) * 8)  # 2048 bytes
    return directory


@pytest.fixture
def db(review_db, insert_ai_annotation, videos_dir, tmp_path):
    review_db.execute("UPDATE Video SET file_path = ? WHERE video_id = 1",
                      (str(videos_dir / "one.mp4"),))
    review_db.execute("UPDATE Video SET file_path = ? WHERE video_id = 2",
                      (str(tmp_path / "outside.mp4"),))
    (tmp_path / "outside.mp4").write_bytes(b"secret")
    review_db.execute("INSERT INTO Frame VALUES ('F1', 1, 24, 1.0)")
    review_db.execute("INSERT INTO FaceDetection (person_id, frame_id, x1, y1, x2, y2,"
                      " det_score) VALUES ('Person_0001', 'F1', 0, 0, 1, 1, 0.9)")
    review_db.execute("UPDATE Label SET is_active = 0 WHERE label_id = ?", (INACTIVE,))
    staff.create_account(review_db, "alex", PASSWORD)
    return review_db


@pytest.fixture
def anon(db, tmp_path, videos_dir):
    db_path = Path(db.execute("PRAGMA database_list").fetchone()[2])
    return TestClient(create_app(db_path, videos_dir))


@pytest.fixture
def client(anon):
    response = anon.post("/api/auth/login", json={"username": "alex", "password": PASSWORD})
    assert response.status_code == 200, response.text
    return anon


# --- Auth ---------------------------------------------------------------------------------

def test_login_sets_strict_httponly_cookie(anon):
    response = anon.post("/api/auth/login", json={"username": "alex", "password": PASSWORD})
    assert response.json()["username"] == "alex" and "password_hash" not in response.text
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert anon.get("/api/auth/me").json()["username"] == "alex"


@pytest.mark.parametrize("username, password", [("alex", "wrong password"),
                                                ("nobody", PASSWORD)])
def test_login_failure_is_generic(anon, username, password):
    response = anon.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid username or password"}


def test_logout_ends_session(client):
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_disabled_account_loses_access(client, db):
    staff.set_active(db, "alex", False)
    assert client.get("/api/videos").status_code == 401


def test_every_operation_requires_session(anon):
    public = {("/api/auth/login", "post"), ("/api/health", "get")}
    schema = anon.get("/api/openapi.json").json()
    checked = 0
    for path, operations in schema["paths"].items():
        concrete = path.replace("{video_id}", "1").replace("{annotation_id}", "1") \
                       .replace("{person_id}", "Person_0001").replace("{clip_id}", "1")
        for method in operations:
            if (path, method) in public:
                continue
            response = anon.request(method.upper(), concrete, json={})
            assert response.status_code == 401, (method, path, response.status_code)
            checked += 1
    assert checked >= 20
    assert anon.get("/api/health").json() == {"status": "ok"}


def test_request_connection_works_across_threads(db, anon):
    # Regression: FastAPI may run the get_db dependency and the route on different threadpool
    # threads; a default sqlite3 connection then raised ProgrammingError (seen in e2e runs).
    import threading
    from types import SimpleNamespace
    from api.auth import get_db
    dependency = get_db(SimpleNamespace(app=anon.app))
    connection = next(dependency)
    errors = []

    def use():
        try:
            connection.execute("SELECT 1").fetchone()
        except Exception as exc:  # noqa: BLE001 - recorded for the assertion below
            errors.append(exc)

    worker = threading.Thread(target=use)
    worker.start()
    worker.join()
    dependency.close()
    assert errors == []


def test_startup_refuses_database_without_staff_tables(tmp_path, videos_dir):
    db_path = tmp_path / "old.sqlite"
    initialize_database(db_path)
    with closing(connect_database(db_path, must_exist=True)) as connection:
        connection.execute("DROP TABLE StaffSession")
    with pytest.raises(ValueError, match="StaffSession"):
        create_app(db_path, videos_dir)


def test_serve_refuses_a_missing_database_with_a_clear_message(tmp_path, capsys):
    from scripts.serve import main as serve_main
    with pytest.raises(SystemExit) as exited:
        serve_main(["--db", str(tmp_path / "missing.sqlite")])
    assert exited.value.code == 2
    assert "does not exist; omit --db to use" in capsys.readouterr().err


def test_serve_binds_localhost_by_default():
    assert serve_parser().parse_args([]).host == "127.0.0.1"


def test_staff_tools_default_to_primary_database(monkeypatch, tmp_path):
    from scripts.import_pipeline_output import build_parser as import_parser
    from scripts.staff import build_parser as staff_parser

    monkeypatch.delenv("TPA_DB", raising=False)
    assert serve_parser().parse_args([]).db == DEFAULT_DB
    assert staff_parser().parse_args(["create", "staff"]).db == DEFAULT_DB
    assert import_parser().parse_args(["--input", "results.json"]).db == DEFAULT_DB
    alternate = tmp_path / "alternate.sqlite"
    monkeypatch.setenv("TPA_DB", str(alternate))
    assert serve_parser().parse_args([]).db == alternate
    assert serve_parser().parse_args(["--db", str(DEFAULT_DB)]).db == DEFAULT_DB


# --- Videos and participants ----------------------------------------------------------------

def test_videos_list_and_detail(client):
    videos = client.get("/api/videos").json()
    assert [v["video_id"] for v in videos] == [1, 2]
    assert videos[0]["participant_count"] == 1 and videos[0]["annotation_counts"]["UNREVIEWED"] == 0
    assert client.get("/api/videos/2").json()["title"] == "two"
    assert client.get("/api/videos/99").status_code == 404
    assert client.get("/api/videos/abc").status_code == 422


def test_video_participants(client):
    (person,) = client.get("/api/videos/1/participants").json()
    assert person["person_id"] == "Person_0001"
    assert person["intervals"] == [{"start_seconds": 1.0, "end_seconds": 1.0,
                                    "detection_count": 1}]
    assert client.get("/api/videos/99/participants").status_code == 404


def test_stream_full_and_range(client):
    full = client.get("/api/videos/1/stream")
    assert full.status_code == 200 and len(full.content) == 2048
    part = client.get("/api/videos/1/stream", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert part.headers["content-range"] == "bytes 0-99/2048"


def test_stream_refuses_outside_and_missing(client, videos_dir):
    assert client.get("/api/videos/2/stream").status_code == 404  # outside the videos dir
    (videos_dir / "one.mp4").unlink()
    assert client.get("/api/videos/1/stream").status_code == 404


def test_stream_seeks_across_chunks_and_reads_the_tail(client, videos_dir):
    content = bytes(range(256)) * 8193
    (videos_dir / "one.mp4").write_bytes(content)
    start, end = 1024 * 1024 - 100, 2 * 1024 * 1024 + 100
    part = client.get("/api/videos/1/stream", headers={"Range": f"bytes={start}-{end}"})
    assert part.status_code == 206 and part.content == content[start:end + 1]
    assert part.headers["content-range"] == f"bytes {start}-{end}/{len(content)}"
    tail = client.get("/api/videos/1/stream", headers={"Range": "bytes=-128"})
    assert tail.status_code == 206 and tail.content == content[-128:]
    assert client.get("/api/videos/1/stream", headers={"Range": f"bytes={len(content)}-"}).status_code == 416


def test_participants(client):
    people = {p["person_id"]: p for p in client.get("/api/participants").json()}
    assert people["Person_0001"]["video_count"] == 1 and len(people) == 3
    detail = client.get("/api/participants/Person_0001").json()
    assert [v["video_id"] for v in detail["videos"]] == [1]
    assert client.get("/api/participants/Person_9999").status_code == 404


# --- Review ---------------------------------------------------------------------------------

def test_create_edit_history_use_session_reviewer(client):
    created = client.post("/api/annotations", json={
        "video_id": 1, "label_id": SINGING, "start_frame": 10, "end_frame": 50,
        "person_id": "Person_0001", "note": "missed"})
    assert created.status_code == 201, created.text
    annotation = created.json()["annotation"]
    assert (annotation["source"], annotation["review_status"]) == ("HUMAN", "ACCEPTED")
    assert created.json()["event"]["reviewer_id"] == "alex"
    edited = client.post(f"/api/annotations/{annotation['annotation_id']}/edit",
                         json={"label_id": SPOKEN})
    assert edited.json()["annotation"]["label_name"] == "Spoken Performance"
    history = client.get(f"/api/annotations/{annotation['annotation_id']}/history").json()
    assert [(e["action"], e["reviewer_id"]) for e in history] == [("CREATED", "alex"),
                                                                 ("EDITED", "alex")]


@pytest.mark.parametrize("action, status", [("accept", "ACCEPTED"), ("reject", "REJECTED"),
                                            ("defer", "DEFERRED")])
def test_status_actions_keep_ai_source(client, db, insert_ai_annotation, action, status):
    annotation_id = insert_ai_annotation(db)
    result = client.post(f"/api/annotations/{annotation_id}/{action}", json={"note": "n"}).json()
    assert (result["annotation"]["source"], result["annotation"]["review_status"]) == ("AI", status)
    assert result["event"]["note"] == "n" and result["event"]["reviewer_id"] == "alex"


def test_ai_edit_becomes_human(client, db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(db)
    result = client.post(f"/api/annotations/{annotation_id}/edit",
                         json={"label_id": SPOKEN}).json()["annotation"]
    assert (result["source"], result["review_status"], result["confidence"]) == \
        ("HUMAN", "EDITED", None)


def test_client_cannot_supply_reviewer(client, db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(db)
    response = client.post(f"/api/annotations/{annotation_id}/accept",
                           json={"reviewer_id": "someone-else"})
    assert response.status_code == 422
    assert client.get(f"/api/annotations/{annotation_id}/history").json() == []


@pytest.mark.parametrize("body", [{"label_id": INACTIVE}, {"end_frame": 999_999},
                                  {"label_id": SUSTAINED}])
def test_invalid_edit_changes_nothing(client, db, insert_ai_annotation, body):
    annotation_id = insert_ai_annotation(db)
    before = client.get(f"/api/annotations/{annotation_id}").json()
    response = client.post(f"/api/annotations/{annotation_id}/edit", json=body)
    assert response.status_code == 400 and response.json()["detail"]
    assert client.get(f"/api/annotations/{annotation_id}").json() == before
    assert client.get(f"/api/annotations/{annotation_id}/history").json() == []


def test_edit_person_null_clears_and_omitted_keeps(client, db, insert_ai_annotation):
    annotation_id = insert_ai_annotation(db)
    kept = client.post(f"/api/annotations/{annotation_id}/edit", json={"start_frame": 101})
    assert kept.json()["annotation"]["person_id"] == "Person_0001"
    cleared = client.post(f"/api/annotations/{annotation_id}/edit", json={"person_id": None})
    assert cleared.json()["annotation"]["person_id"] is None


def test_missing_annotation_is_404(client):
    assert client.get("/api/annotations/999").status_code == 404
    assert client.get("/api/annotations/999/history").status_code == 404
    assert client.post("/api/annotations/999/accept", json={}).status_code == 404


def test_annotation_filters_and_rejected_hidden(client, db, insert_ai_annotation):
    keep = insert_ai_annotation(db)
    gone = insert_ai_annotation(db, review_status="REJECTED")
    insert_ai_annotation(db, video_id=2, person_id="Person_0002", label_id=SUSTAINED)
    assert [a["annotation_id"] for a in client.get("/api/annotations?video_id=1").json()] == [keep]
    everything = client.get("/api/annotations?video_id=1&include_rejected=true").json()
    assert {a["annotation_id"] for a in everything} == {keep, gone}
    assert len(client.get("/api/annotations?category=observation").json()) == 1
    assert len(client.get("/api/annotations?person_id=Person_0002").json()) == 1
    assert client.get("/api/annotations?review_status=BOGUS").status_code == 422


# --- Labels, clips, exports -----------------------------------------------------------------

def test_labels(client):
    active = client.get("/api/labels").json()
    assert len(active) == 17 and all(label["is_active"] for label in active)
    assert len(client.get("/api/labels?include_inactive=true").json()) == 18
    assert {label["category"] for label in client.get("/api/labels?category=activity").json()} \
        == {"activity"}


def test_clips_by_priority(client, db):
    db.executemany(
        "INSERT INTO ReviewClip (clip_id, video_id, start_frame, end_frame, priority_score,"
        " priority_method, created_at) VALUES (?, 1, ?, ?, ?, ?, 'now')",
        [(1, 0, 10, None, None), (2, 20, 30, 2.07, "m@1"), (3, 40, 50, 0.5, "m@1")])
    db.execute("INSERT INTO ReviewClipParticipant VALUES (3, 'Person_0002')")
    ordered = client.get("/api/clips?order=priority").json()
    assert [c["clip_id"] for c in ordered] == [2, 3, 1]
    assert ordered[0]["priority_score"] == 2.07 and "confidence" not in ordered[0]
    assert [c["clip_id"] for c in client.get("/api/clips?person_id=Person_0002").json()] == [3]
    assert client.get("/api/clips?order=bogus").status_code == 422


def test_clip_detail_limit_and_imports(client, db):
    import hashlib
    import json as _json
    from analysis_db.pipeline_import import import_file, parse_import_file
    text = _json.dumps({"format": "tpa-review-import/1",
                        "pipeline": {"name": "synthetic-fixture", "version": "1"},
                        "videos": [{"filename": "one.mp4", "clips": [
                            {"key": f"k{i}", "start_frame": i, "end_frame": i + 5,
                             "participants": ["Person_0001"],
                             "priority": {"score": float(i), "method": "m@1"}} for i in range(3)]}]})
    assert client.get("/api/imports").json() == []
    import_file(db, parse_import_file(text), source_name="f.json",
                sha256=hashlib.sha256(text.encode()).hexdigest())
    top = client.get("/api/clips?order=priority&limit=2").json()
    assert [c["priority_score"] for c in top] == [2.0, 1.0]
    one = client.get(f"/api/clips/{top[0]['clip_id']}").json()
    assert one["person_ids"] == ["Person_0001"] and one["priority_method"] == "m@1"
    assert client.get("/api/clips/9999").status_code == 404
    assert client.get("/api/clips?limit=0").status_code == 422
    (run,) = client.get("/api/imports").json()
    assert run["pipeline_name"] == "synthetic-fixture" and run["counts"]["clips_inserted"] == 3


def test_exports(client, db, insert_ai_annotation):
    insert_ai_annotation(db)
    insert_ai_annotation(db, review_status="REJECTED")
    response = client.get("/api/exports/annotations?format=csv")
    assert response.headers["content-disposition"] == 'attachment; filename="annotations.csv"'
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1 and rows[0]["label_name"] == "Singing"
    assert len(client.get("/api/exports/annotations?format=json&include_rejected=true")
               .json()) == 2
    annotation_id = rows[0]["annotation_id"]
    client.post(f"/api/annotations/{annotation_id}/accept", json={})
    history = json.loads(client.get("/api/exports/history?format=json").text)
    assert [e["reviewer_id"] for e in history] == ["alex"]
    assert client.get("/api/exports/history?format=csv").text.startswith("event_id,")
    assert client.get("/api/exports/history?format=xml").status_code == 422


# --- Real database (skipped without the private dataset) -------------------------------------

@pytest.mark.skipif(not DEFAULT_DB.exists(), reason="real analysis database not present")
def test_real_database_reads_are_interactive(tmp_path, videos_dir):
    db_path = tmp_path / "real.sqlite"
    shutil.copy(DEFAULT_DB, db_path)
    initialize_database(db_path)
    with closing(connect_database(db_path, must_exist=True)) as connection:
        staff.create_account(connection, "alex", PASSWORD)
    client = TestClient(create_app(db_path, videos_dir))
    client.post("/api/auth/login", json={"username": "alex", "password": PASSWORD})
    for path, expected in (("/api/videos", 12), ("/api/participants", 100)):
        started = time.perf_counter()
        assert len(client.get(path).json()) == expected
        assert time.perf_counter() - started < 1.0
    longest = max(client.get("/api/videos").json(), key=lambda v: v["detection_count"])
    started = time.perf_counter()
    assert client.get(f"/api/videos/{longest['video_id']}/participants").json()
    assert time.perf_counter() - started < 1.0
    detail = client.get("/api/participants/Person_0001").json()
    assert len(detail["videos"]) >= 1


def test_openapi_script_prints_schema():
    import subprocess
    import sys
    script = Path(__file__).resolve().parents[1] / "scripts" / "openapi.py"
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "/api/videos" in json.loads(result.stdout)["paths"]


@pytest.fixture
def stored(db):
    db.execute("INSERT INTO Clip(clip_id,video_id,start_time_seconds,end_time_seconds,created_at) VALUES (1,1,0.25,2.75,'now')")
    db.execute("INSERT INTO Clip(clip_id,video_id,start_time_seconds,end_time_seconds,created_at) VALUES (2,1,3.0,5.0,'now')")
    db.execute("INSERT INTO ClipPerson VALUES (1,'Person_0001')")
    db.execute("INSERT INTO ClipPerson VALUES (2,'Person_0002')")
    db.execute("INSERT INTO Activity(activity_id,frame_id,window_start_seconds,window_end_seconds,"
               "sample_count,activity_label,score,result_json,sampling_json,config_json,config_hash,input_hash)"
               " VALUES(1,'F1',0,10,32,'Stored singing',0.8,'{}','{}','{}','c','i')")
    db.execute("INSERT INTO Engagement(detection_id,positive_score,neutral_score,negative_score)"
               " VALUES(1,0.6,0.3,0.1)")
    return db


def test_stored_clip_reads_filters_and_separate_review_ids(client, stored):
    stored.execute("INSERT INTO ReviewClip(clip_id,video_id,start_frame,end_frame,created_at)"
                   " VALUES(1,1,240,480,'now')")
    clips = client.get('/api/person-clips').json()
    assert [c['clip_id'] for c in clips] == [1, 2]
    assert clips[0]['start_seconds'] == 0.25
    assert clips[0]['person_ids'] == ['Person_0001']
    assert client.get('/api/person-clips?person_id=Person_0002').json() == [clips[1]]
    assert client.get('/api/person-clips?video_id=2').json() == []
    assert client.get('/api/person-clips?limit=1&offset=1').json() == [clips[1]]
    assert client.get('/api/person-clips/1').json() == clips[0]
    assert client.get('/api/clips/1').json()['start_frame'] == 240
    assert client.get('/api/videos/1').json()['person_clip_count'] == 2
    assert client.get('/api/videos/1').json()['clip_count'] == 1
    assert stored.execute('SELECT count(*) FROM Annotation').fetchone() == (0,)


def test_stored_clip_summary_uses_current_corrected_values(client, stored):
    from analysis_db.corrections import correct_activity, correct_engagement
    summary = client.get('/api/person-clips/1/summary').json()
    assert summary['dominant_activity'] == 'Stored singing'
    assert summary['activity_distribution'] == {'Stored singing': 1.0}
    assert summary['visible_affect'] == {'positive': 0.6, 'neutral': 0.3, 'negative': 0.1,
                                       'observation_count': 1}
    correct_activity(stored, 1, 'Corrected activity', changed_by='staff')
    correct_engagement(stored, 1, 0.2, 0.7, 0.1, changed_by='staff')
    summary = client.get('/api/person-clips/1/summary').json()
    assert summary['dominant_activity'] == 'Corrected activity'
    assert summary['visible_affect']['positive'] == 0.2
    assert client.get('/api/person-clips/2/summary').json()['visible_affect']['observation_count'] == 0


def _synthetic_video(path, seconds=4, fps=10):
    import av
    import numpy as np
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=fps)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for index in range(seconds * fps):
            shade = np.full((48, 64, 3), index * 6 % 256, dtype=np.uint8)  # plain synthetic colour
            for packet in stream.encode(av.VideoFrame.from_ndarray(shade, format="rgb24")):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_clip_thumbnail_is_a_small_uncached_jpeg_of_the_clip_start(client, stored, videos_dir):
    _synthetic_video(videos_dir / "one.mp4")
    response = client.get('/api/person-clips/1/thumbnail')
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'image/jpeg'
    assert response.headers['cache-control'] == 'no-store'
    assert response.content[:2] == b'\xff\xd8'
    from PIL import Image
    assert Image.open(io.BytesIO(response.content)).size == (64, 48)  # never enlarged
    assert client.get('/api/person-clips/999/thumbnail').status_code == 404
    (videos_dir / "one.mp4").unlink()
    assert client.get('/api/person-clips/1/thumbnail').status_code == 404
    client.post('/api/auth/logout')
    assert client.get('/api/person-clips/1/thumbnail').status_code == 401


def test_processing_progress_counts_what_each_stage_has_stored(client, stored):
    # Fixture: video 1 has one frame with a face (F1); it has an Activity result and an Engagement score.
    stored.execute("INSERT INTO Frame VALUES ('F2', 1, 48, 2.0)")
    stored.execute("INSERT INTO FaceDetection(person_id,frame_id,x1,y1,x2,y2,det_score) VALUES('Person_0001','F2',0,0,1,1,0.9)")
    stored.execute("INSERT INTO Frame VALUES ('EMPTY', 1, 72, 3.0)")  # no face: not on the activity work list
    progress = {v['video_id']: {s['stage']: (s['done'], s['total']) for s in v['stages']}
                for v in client.get('/api/processing').json()}
    assert progress[1] == {'activity': (1, 2), 'engagement': (1, 2), 'clips': (0, 1)}
    assert progress[2] == {'activity': (0, 0), 'engagement': (0, 0), 'clips': (0, 1)}
    stored.execute("INSERT INTO ClipGeneration VALUES (1, 5, 'now')")
    assert client.get('/api/processing').json()[0]['stages'][2] == {'stage': 'clips', 'done': 1, 'total': 1}
    client.post('/api/auth/logout')
    assert client.get('/api/processing').status_code == 401


def test_activity_counts_use_current_labels_most_frequent_first(client, stored):
    for index, label in enumerate(['Acting', 'Acting', 'Dancing'], start=2):
        stored.execute("INSERT INTO Frame VALUES (?,1,?,?)", (f'A{index}', index * 24, float(index)))
        stored.execute("INSERT INTO Activity(frame_id,window_start_seconds,window_end_seconds,sample_count,"
                       "activity_label,score,result_json,sampling_json,config_json,config_hash,input_hash)"
                       " VALUES(?,?,?,32,?,0.5,'{}','{}','{}','c','i')", (f'A{index}', index, index + 1, label))
    # Windows: Stored singing 0–10 s (covers F1 at 1.0 s, positive 0.6); Acting 2–3 s and 3–4 s; Dancing 4–5 s.
    assert [(c['activity_label'], c['count']) for c in client.get('/api/activity-counts').json()] == [
        ('Acting', 2), ('Dancing', 1), ('Stored singing', 1)]
    by_label = {c['activity_label']: c for c in client.get('/api/activity-counts').json()}
    assert by_label['Stored singing']['mean_positive_score'] == pytest.approx(0.6)
    assert by_label['Stored singing']['observation_count'] == 1
    assert by_label['Acting']['mean_positive_score'] is None and by_label['Acting']['observation_count'] == 0
    stored.execute("INSERT INTO FaceDetection(person_id,frame_id,x1,y1,x2,y2,det_score) VALUES('Person_0002','A2',0,0,1,1,0.9)")
    stored.execute("INSERT INTO Engagement(detection_id,positive_score,neutral_score,negative_score)"
                   " VALUES((SELECT MAX(detection_id) FROM FaceDetection),0.2,0.7,0.1)")
    by_label = {c['activity_label']: c for c in client.get('/api/activity-counts').json()}
    assert by_label['Acting']['mean_positive_score'] == pytest.approx(0.2)  # A2 at 2.0 s is in the 2–3 s window only
    assert by_label['Stored singing']['mean_positive_score'] == pytest.approx(0.4)  # 0–10 s now holds 0.6 and 0.2
    from analysis_db.corrections import correct_activity
    correct_activity(stored, 1, 'Dancing', changed_by='staff')
    counts = {c['activity_label']: c['count'] for c in client.get('/api/activity-counts').json()}
    assert counts == {'Acting': 2, 'Dancing': 2}


def test_clip_accept_and_defer_change_only_status_and_append_history(client, stored):
    assert client.get('/api/person-clips/1').json()['review_status'] == 'UNREVIEWED'
    assert client.post('/api/person-clips/1/accept').json()['review_status'] == 'ACCEPTED'
    assert client.post('/api/person-clips/1/defer').json()['review_status'] == 'DEFERRED'
    assert client.get('/api/person-clips/2').json()['review_status'] == 'UNREVIEWED'
    assert client.get('/api/videos/1').json()['clip_status_counts'] == {
        'UNREVIEWED': 1, 'ACCEPTED': 0, 'EDITED': 0, 'DEFERRED': 1}
    assert [c['clip_id'] for c in client.get('/api/person-clips?review_status=DEFERRED').json()] == [1]
    assert [c['clip_id'] for c in client.get('/api/person-clips?review_status=UNREVIEWED').json()] == [2]
    assert client.get('/api/person-clips?review_status=ACCEPTED').json() == []
    assert client.get('/api/person-clips/status-counts').json() == {
        'UNREVIEWED': 1, 'ACCEPTED': 0, 'EDITED': 0, 'DEFERRED': 1}
    events = stored.execute("SELECT action,previous_status,resulting_status,reviewer_id FROM ClipReviewEvent"
                            " ORDER BY event_id").fetchall()
    assert events == [('ACCEPT', 'UNREVIEWED', 'ACCEPTED', 'alex'), ('DEFER', 'ACCEPTED', 'DEFERRED', 'alex')]
    assert stored.execute('SELECT COUNT(*) FROM ActivityAudit').fetchone() == (0,)
    summary = client.get('/api/person-clips/1/summary').json()
    assert summary['dominant_activity'] == 'Stored singing'


def test_clip_edit_preserves_model_activity_and_audits_human_changes(client, stored):
    response = client.post('/api/person-clips/1/edit', json={
        'activity_label': 'Dancing', 'positive_score': 0.9, 'neutral_score': 0.1, 'negative_score': 0.0})
    assert response.status_code == 200, response.text
    assert response.json()['review_status'] == 'EDITED'
    summary = client.get('/api/person-clips/1/summary').json()
    assert summary['dominant_activity'] == 'Dancing'
    assert summary['visible_affect']['positive'] == 0.9
    assert summary['activity_source'] == 'HUMAN'
    assert stored.execute('SELECT activity_label FROM Activity').fetchall() == [('Stored singing',)]
    assert stored.execute('SELECT COUNT(*) FROM ActivityAudit').fetchone() == (0,)
    assert stored.execute('SELECT start_frame,end_frame,source FROM Annotation').fetchall() == [(24, 24, 'HUMAN')]
    assert client.get('/api/person-clips/2/summary').json()['dominant_activity'] == 'Stored singing'
    assert stored.execute('SELECT old_positive_score,new_positive_score,changed_by FROM EngagementAudit').fetchall() == [
        (0.6, 0.9, 'alex')]
    assert stored.execute('SELECT action,resulting_status FROM ClipReviewEvent').fetchall() == [('EDIT', 'EDITED')]


def test_clip_edit_can_add_a_new_activity_label_atomically(client, stored):
    body = {'activity_label': '  Beatboxing ', 'create_activity_label': True}
    response = client.post('/api/person-clips/1/edit', json=body)
    assert response.status_code == 200, response.text
    assert client.get('/api/person-clips/1/summary').json()['dominant_activity'] == 'Beatboxing'
    names = [l['name'] for l in client.get('/api/labels?category=activity').json()]
    assert names.count('Beatboxing') == 1
    assert client.post('/api/person-clips/2/edit', json={**body, 'activity_label': 'beatboxing'}).status_code == 400
    # A failed edit leaves no new label behind.
    assert client.post('/api/person-clips/2/edit', json={'activity_label': ' ', 'create_activity_label': True}).status_code == 400
    # No analyzed frames belong to clip 3, so the new label rolls back with the failed edit.
    stored.execute("INSERT INTO Clip(clip_id,video_id,start_time_seconds,end_time_seconds,created_at)"
                   " VALUES (3,1,10.0,12.0,'now')")
    assert client.post('/api/person-clips/3/edit', json={'activity_label': 'Juggling',
                                                          'create_activity_label': True}).status_code == 400
    assert 'Juggling' not in [l['name'] for l in client.get('/api/labels').json()]


def test_manual_activity_labels_are_frame_scoped_reusable_and_keep_history(client, stored):
    stored.execute("INSERT INTO Frame VALUES('start',1,6,0.25)")
    stored.execute("INSERT INTO Frame VALUES('end',1,66,2.75)")
    stored.execute("INSERT INTO Frame VALUES('next',1,72,3.0)")
    before = stored.execute('SELECT * FROM Activity').fetchall()
    response = client.post('/api/person-clips/1/edit', json={'activity_label': 'Beatboxing', 'create_activity_label': True})
    assert response.status_code == 200, response.text
    assert stored.execute('SELECT start_frame,end_frame,source,confidence FROM Annotation').fetchall() == [(6, 24, 'HUMAN', None)]
    assert stored.execute('SELECT * FROM Activity').fetchall() == before
    assert client.get('/api/person-clips/2/summary').json()['dominant_activity'] == 'Stored singing'
    assert client.get('/api/person-clips/2').json()['review_status'] == 'UNREVIEWED'
    assert client.post('/api/person-clips/1/edit', json={'activity_label': 'Beatboxing'}).status_code == 400
    assert client.post('/api/person-clips/1/edit', json={'activity_label': 'Dancing'}).status_code == 200
    assert stored.execute('SELECT COUNT(*) FROM Annotation').fetchone() == (1,)
    assert stored.execute('SELECT action,new_source FROM ReviewEvent ORDER BY event_id').fetchall() == [('CREATED', 'HUMAN'), ('EDITED', 'HUMAN')]
    assert client.post('/api/person-clips/2/edit', json={'activity_label': 'Beatboxing'}).status_code == 200
    assert client.get('/api/person-clips/1/summary').json()['dominant_activity'] == 'Dancing'
    assert client.get('/api/person-clips/2/summary').json()['dominant_activity'] == 'Beatboxing'
    names = [label['name'] for label in client.get('/api/labels?category=activity').json()]
    assert 'Dancing' in names and names.count('Beatboxing') == 1
    assert stored.execute('SELECT * FROM Activity').fetchall() == before
    annotations = client.get('/api/annotations?video_id=1&category=activity').json()
    assert len(annotations) == 2 and all(a['source'] == 'HUMAN' for a in annotations)
    exported = client.get('/api/exports/annotations?format=json').json()
    assert {a['label_name'] for a in exported} == {'Dancing', 'Beatboxing'}
    assert client.get('/api/exports/database/activity?format=json').json()[0]['activity_label'] == 'Stored singing'


@pytest.mark.parametrize('query,identities', [('sing', [1, 2]), ('SING', [1, 2]), ('#2', [2]), ('0002', [2]),
    ('%_', [1, 2]), ("' OR 1=1 --", []), ('missing', []), ('  ', [1, 2, 3])])
def test_clip_search_matches_titles_or_exact_ids_with_consistent_counts(client, stored, query, identities):
    stored.execute("UPDATE Video SET title='Singing %_ camp' WHERE video_id=1")
    stored.execute("UPDATE Video SET title='Other video' WHERE video_id=2")
    stored.execute("INSERT INTO Clip(clip_id,video_id,start_time_seconds,end_time_seconds,created_at) VALUES(3,2,0,5,'now')")
    stored.execute("UPDATE Clip SET review_status='ACCEPTED' WHERE clip_id=2")
    result = client.get('/api/person-clips', params={'search': query})
    assert result.status_code == 200
    assert [row['clip_id'] for row in result.json()] == identities
    counts = client.get('/api/person-clips/status-counts', params={'search': query}).json()
    assert sum(counts.values()) == len(identities)
    filtered = client.get('/api/person-clips', params={'search': query, 'review_status': 'ACCEPTED'}).json()
    assert [row['clip_id'] for row in filtered] == ([2] if 2 in identities else [])
    page = client.get('/api/person-clips', params={'search': query, 'limit': 1, 'offset': 1}).json()
    assert [row['clip_id'] for row in page] == identities[1:2]


def test_clip_search_refuses_overlong_queries(client):
    for path in ('/api/person-clips', '/api/person-clips/status-counts'):
        assert client.get(path, params={'search': 'x' * 201}).status_code == 422


@pytest.mark.parametrize('body', [{}, {'activity_label': 'Not a label'}, {'positive_score': 0.5},
                                  {'activity_label': 'Stored singing'}, {'reviewer_id': 'mallory'},
                                  {'positive_score': 2, 'neutral_score': 0, 'negative_score': 0}])
def test_clip_edit_rejects_invalid_or_no_op_edits_without_writing(client, stored, body):
    assert client.post('/api/person-clips/1/edit', json=body).status_code in (400, 422)
    assert client.get('/api/person-clips/1').json()['review_status'] == 'UNREVIEWED'
    for table in ('ClipReviewEvent', 'ActivityAudit', 'EngagementAudit'):
        assert stored.execute(f'SELECT COUNT(*) FROM {table}').fetchone() == (0,)


def test_clip_review_requires_sign_in_and_existing_clip(anon, client, stored):
    assert client.post('/api/person-clips/999/accept').status_code == 404
    client.post('/api/auth/logout')
    assert client.post('/api/person-clips/1/accept').status_code == 401


@pytest.mark.parametrize('dataset,count', [('clips', 2), ('activity', 1), ('engagement', 1),
                                          ('activity-history', 0), ('engagement-history', 0),
                                          ('clip-review-history', 0)])
def test_database_exports_read_stored_rows_and_empty_headers(client, stored, dataset, count):
    base = f'/api/exports/database/{dataset}'
    response = client.get(base + '?format=csv')
    assert response.status_code == 200
    assert len(list(csv.DictReader(io.StringIO(response.text)))) == count
    assert len(response.text.splitlines()[0].split(',')) > 1
    assert len(client.get(base + '?format=json').json()) == count
    assert 'password' not in response.text and 'token' not in response.text


@pytest.mark.parametrize('path,status', [('/person-clips/999', 404),
    ('/person-clips/999/summary', 404), ('/person-clips?limit=0', 422),
    ('/person-clips?offset=-1', 422), ('/person-clips?review_status=REJECTED', 422), ('/exports/database/StaffAccount?format=csv', 422),
    ('/exports/database/clips?format=xml', 422)])
def test_stored_read_validation(client, stored, path, status):
    assert client.get('/api' + path).status_code == status


def test_impact_uses_all_clip_members_and_observation_mean_with_half_open_bounds(client, stored):
    stored.execute("INSERT INTO ClipPerson VALUES(1,'Person_0002')")
    assert client.get('/api/person-clips/1').json()['impact_score'] == pytest.approx(math.log1p(2.5 / 3) * 1.5 ** 2 * 0.6)  # clip 1 lasts 2.5 s
    rows = [('MID', 1.5, 'Person_0001', 0.3), ('LATE', 2.0, 'Person_0001', 0.9),
            ('F1', 1.0, 'Person_0002', 0.2), ('START', 0.25, 'Person_0002', 0.0),
            ('END', 2.75, 'Person_0001', 1.0), ('F1', 1.0, 'Person_0003', 1.0)]
    for frame, moment, person, positive in rows:
        stored.execute('INSERT OR IGNORE INTO Frame VALUES (?,1,?,?)', (frame, round(moment * 24), moment))
        detection = stored.execute('INSERT INTO FaceDetection(person_id,frame_id,x1,y1,x2,y2,det_score)'
                                   ' VALUES(?,?,0,0,1,1,0.9)', (person, frame)).lastrowid
        stored.execute('INSERT INTO Engagement(detection_id,positive_score,neutral_score,negative_score)'
                       ' VALUES(?,?,0,0)', (detection, positive))
    clip = client.get('/api/person-clips/1').json()
    assert clip['mean_positive_score'] == pytest.approx(0.4)
    assert len(clip['person_ids']) == 2  # repeated detections do not increase N
    assert clip['impact_score'] == pytest.approx(math.log1p(2.5 / 3) * 1.5 ** 2 * 0.4)
    summary = client.get('/api/person-clips/1/summary').json()
    assert summary['impact_score'] == pytest.approx(clip['impact_score'])
    assert summary['visible_affect']['positive'] == pytest.approx(clip['mean_positive_score'])
    from analysis_db.corrections import correct_engagement
    correct_engagement(stored, 1, 0.1, 0.3, 0.1)
    assert client.get('/api/person-clips/1').json()['impact_score'] == pytest.approx(math.log1p(2.5 / 3) * 1.5 ** 2 * 0.3)
    assert client.get('/api/person-clips/2').json()['impact_score'] is None


def test_missing_scores_are_unscored_and_zero_scores_are_valid(client, stored):
    stored.execute('UPDATE Engagement SET positive_score=0')
    assert client.get('/api/person-clips/1').json()['impact_score'] == 0
    missing = client.get('/api/person-clips/2').json()
    assert missing['mean_positive_score'] is None and missing['impact_score'] is None
    assert client.get('/api/person-clips/2/summary').json()['impact_score'] is None


def test_human_annotation_total_counts_source_not_acceptance(client, db, insert_ai_annotation):
    insert_ai_annotation(db, review_status='ACCEPTED')
    assert client.get('/api/videos/1').json()['human_annotation_count'] == 0
    insert_ai_annotation(db, source='HUMAN', review_status='ACCEPTED')
    assert client.get('/api/videos/1').json()['human_annotation_count'] == 1


def test_human_annotation_total_counts_each_corrected_record_once(client, stored, insert_ai_annotation):
    from analysis_db.corrections import correct_activity, correct_engagement
    assert client.get('/api/videos/1').json()['human_annotation_count'] == 0
    correct_activity(stored, 1, 'Updated singing', changed_by='staff')
    correct_activity(stored, 1, 'Updated again', changed_by='staff')
    correct_engagement(stored, 1, 0.2, 0.7, 0.1, changed_by='staff')
    correct_engagement(stored, 1, 0.3, 0.6, 0.1, changed_by='staff')
    assert client.get('/api/videos/1').json()['human_annotation_count'] == 2
    assert client.get('/api/videos/2').json()['human_annotation_count'] == 0
    insert_ai_annotation(stored, source='HUMAN')
    assert client.get('/api/videos/1').json()['human_annotation_count'] == 3
