import csv
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
                       .replace("{person_id}", "Person_0001")
        for method in operations:
            if (path, method) in public:
                continue
            response = anon.request(method.upper(), concrete, json={})
            assert response.status_code == 401, (method, path, response.status_code)
            checked += 1
    assert checked >= 20
    assert anon.get("/api/health").json() == {"status": "ok"}


def test_startup_refuses_database_without_staff_tables(tmp_path, videos_dir):
    db_path = tmp_path / "old.sqlite"
    initialize_database(db_path)
    with closing(connect_database(db_path, must_exist=True)) as connection:
        connection.execute("DROP TABLE StaffSession")
    with pytest.raises(ValueError, match="StaffSession"):
        create_app(db_path, videos_dir)


def test_serve_binds_localhost_by_default():
    assert serve_parser().parse_args([]).host == "127.0.0.1"


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
