from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from analysis_db.storage import initialize_database


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


@pytest.fixture
def repositories(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Checkpoint Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "checkpoint@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Checkpoint Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "checkpoint@example.invalid")
    main = tmp_path / "main"
    main.mkdir()
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(main)], check=True, capture_output=True)
    initialize_database(main / "data/analysis.sqlite")
    (main / "README.md").write_text("original\n")
    (main / ".gitignore").write_text("results/\n")
    git(main, "add", ".")
    git(main, "commit", "-m", "initial")
    git(main, "remote", "add", "origin", str(remote))
    git(main, "push", "-u", "origin", "main")
    worktree = tmp_path / "worktree"
    git(main, "worktree", "add", "-b", "inference", str(worktree))
    return main, worktree


def test_checkpoint_push_preserves_concurrent_main_commit_and_staged_work(repositories):
    from scripts.run_activity_checkpoints import publish_checkpoint
    main, worktree = repositories
    (main / "frontend.txt").write_text("parallel work\n")
    git(main, "add", "frontend.txt")
    git(main, "commit", "-m", "frontend")
    (main / "README.md").write_text("uncommitted user work\n")
    git(main, "add", "README.md")
    with sqlite3.connect(worktree / "data/analysis.sqlite") as c:
        c.execute("INSERT INTO Person VALUES('new-person')")
    published = publish_checkpoint(worktree, main, "data: checkpoint test")
    assert git(main, "rev-parse", "HEAD") == published
    assert git(main, "rev-parse", "origin/main") == published
    assert (main / "frontend.txt").read_text() == "parallel work\n"
    assert (main / "README.md").read_text() == "uncommitted user work\n"
    assert git(main, "diff", "--cached", "--name-only") == "README.md"
    assert git(main, "show", "HEAD:README.md") == "original"
    with sqlite3.connect(main / "data/analysis.sqlite") as c:
        assert c.execute("SELECT person_id FROM Person").fetchall() == [("new-person",)]
    assert git(worktree, "status", "--porcelain", "--untracked-files=no") == ""


def test_checkpoint_refuses_unrelated_worktree_changes(repositories):
    from scripts.run_activity_checkpoints import publish_checkpoint
    main, worktree = repositories
    before = git(main, "rev-parse", "HEAD")
    (worktree / "README.md").write_text("unexpected code change\n")
    with pytest.raises(RuntimeError, match="Unrelated"):
        publish_checkpoint(worktree, main, "data: should not commit")
    assert git(main, "rev-parse", "HEAD") == before


def test_checkpoint_refuses_untracked_code(repositories):
    from scripts.run_activity_checkpoints import publish_checkpoint
    main, worktree = repositories
    (worktree / "surprise.py").write_text("print('unexpected code')\n")
    with pytest.raises(RuntimeError, match="Unrelated"):
        publish_checkpoint(worktree, main, "data: must not publish")


def test_restart_retries_committed_but_unpushed_checkpoint(repositories, monkeypatch):
    import scripts.run_activity_checkpoints as module
    main, worktree = repositories
    with sqlite3.connect(worktree / "data/analysis.sqlite") as c:
        c.execute("INSERT INTO Person VALUES('saved')")
    original = module.git
    def fail_push(root, *args):
        if args == ("push", "origin", "main"):
            raise subprocess.CalledProcessError(1, ["git", *args], stderr="temporary failure")
        return original(root, *args)
    monkeypatch.setattr(module, "git", fail_push)
    with pytest.raises(subprocess.CalledProcessError):
        module.publish_checkpoint(worktree, main, "data: final chunk")
    assert git(main, "rev-parse", "HEAD") != git(main, "rev-parse", "origin/main")
    monkeypatch.setattr(module, "git", original)
    published = module.reconcile_publication(worktree, main)
    assert git(main, "rev-parse", "origin/main") == published


def test_no_pending_work_publishes_dirty_recovered_database(repositories, monkeypatch):
    import scripts.run_activity_checkpoints as module
    main, worktree = repositories
    with sqlite3.connect(worktree / "data/analysis.sqlite") as c:
        c.execute("INSERT INTO Person VALUES('recovered')")
    monkeypatch.setattr(module, "code_signature", lambda root: ("same code",))
    monkeypatch.setattr(module.runner, "run_activity", lambda *a, **k:
                        SimpleNamespace(failed=0,written=0,report={"remaining_frames":0}))
    module.run_loop(worktree, main)
    with sqlite3.connect(main / "data/analysis.sqlite") as c:
        assert c.execute("SELECT person_id FROM Person").fetchall() == [("recovered",)]
    assert git(main,"rev-parse","HEAD") == git(main,"rev-parse","origin/main")


def test_runtime_reuses_model_and_index_between_chunks(monkeypatch, tmp_path):
    from scripts.run_activity_checkpoints import reuse_runtime
    from activity_pipeline import runner
    models, indexes = [], []
    def model(**kwargs):
        value = object()
        models.append(value)
        return value
    def index(path):
        value = SimpleNamespace(fallback_count=0, cancel_event=None)
        indexes.append(value)
        return value
    monkeypatch.setattr(runner, "XCLIPClassifier", model)
    monkeypatch.setattr(runner, "IndexedTemporalSampler", index)
    with reuse_runtime():
        assert runner.XCLIPClassifier(device="cpu", precision="fp32") is runner.XCLIPClassifier(device="cpu", precision="fp32")
        first = runner.IndexedTemporalSampler(tmp_path / "video.mp4")
        first.fallback_count, first.cancel_event = 9, object()
        assert runner.IndexedTemporalSampler(tmp_path / "video.mp4") is first
        assert first.fallback_count == 0 and first.cancel_event is None
    assert len(models) == len(indexes) == 1
    assert runner.XCLIPClassifier is model
