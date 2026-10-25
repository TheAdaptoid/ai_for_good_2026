"""Run 500-instance chunks and publish each validated SQLite checkpoint."""

import argparse
from contextlib import contextmanager
import hashlib
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from activity_pipeline import runner
from analysis_db.activity_results import canonical_json, config_fingerprint
from analysis_db.paths import REPOSITORY_ROOT

TRACKED_DB = "data/analysis.sqlite"
PRESERVED_TABLES = ("Video", "Frame", "Person", "FaceDetection", "Engagement")


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True,
        timeout=180,
    )
    if result.stderr.strip():
        print(result.stderr.strip(), flush=True)
    return result.stdout.strip()


def check_workspace(worktree, main_root):
    worktree, main_root = Path(worktree), Path(main_root)
    if worktree.resolve() == main_root.resolve():
        raise RuntimeError("Inference checkpoints require an isolated worktree")
    branch = git(worktree, "branch", "--show-current")
    if not branch or branch == "main" or git(main_root, "branch", "--show-current") != "main":
        raise RuntimeError("Expected an inference branch and main checked out in the main workspace")
    changed = set(git(worktree, "diff", "--name-only").splitlines())
    if (changed - {TRACKED_DB} or git(worktree, "diff", "--cached", "--name-only")
            or git(worktree, "ls-files", "--others", "--exclude-standard")):
        raise RuntimeError("Unrelated worktree, untracked, or staged changes prevent checkpoint publication")
    return branch, changed


def synchronize_main(worktree, main_root):
    """Retry pending publication even when no new inference is needed."""
    branch, _ = check_workspace(worktree, main_root)
    git(worktree, "fetch", "origin")
    print(git(worktree, "merge", "--no-edit", "main"), flush=True)
    print(git(worktree, "merge", "--no-edit", "origin/main"), flush=True)
    print(git(main_root, "merge", "--ff-only", branch), flush=True)
    git(main_root, "push", "origin", "main")
    return git(main_root, "rev-parse", "origin/main")


def publish_checkpoint(worktree, main_root, message):
    """Commit only the DB, integrate concurrent main changes, and push main."""
    worktree, main_root = Path(worktree), Path(main_root)
    _, changed = check_workspace(worktree, main_root)
    if TRACKED_DB not in changed:
        raise RuntimeError("No SQLite checkpoint changes to publish")
    if (worktree / TRACKED_DB).stat().st_size >= 100 * 1024 * 1024:
        raise RuntimeError("SQLite checkpoint reached GitHub's 100 MiB file limit; results remain saved locally")
    print(git(worktree, "status", "--short"), flush=True)
    print(git(worktree, "diff", "--numstat", "--", TRACKED_DB), flush=True)
    print(git(worktree, "log", "--oneline", "-10"), flush=True)
    git(worktree, "add", "--", TRACKED_DB)
    staged = git(worktree, "diff", "--cached", "--name-only").splitlines()
    if staged != [TRACKED_DB]:
        raise RuntimeError("Checkpoint index contains unexpected files")
    print(git(worktree, "commit", "-m", message), flush=True)
    # Integrate in the clean inference worktree, then fast-forward main. This
    # preserves unrelated staged/unstaged work in the user's main checkout.
    return synchronize_main(worktree, main_root)


def reconcile_publication(worktree, main_root):
    _, changed = check_workspace(worktree, main_root)
    if TRACKED_DB in changed:
        return publish_checkpoint(worktree, main_root, "data: recover completed activity checkpoint")
    return synchronize_main(worktree, main_root)


@contextmanager
def reuse_runtime():
    """Keep model/indexes in this process, restoring the runner factories on exit."""
    original_model, original_index = runner.XCLIPClassifier, runner.IndexedTemporalSampler
    models, indexes = {}, {}

    def cached_model(**kwargs):
        key = tuple(sorted(kwargs.items()))
        if key not in models:
            models[key] = original_model(**kwargs)
        else:
            print("Reusing loaded X-CLIP model", flush=True)
        return models[key]

    def cached_index(path):
        key = Path(path).resolve()
        if key not in indexes:
            indexes[key] = original_index(path)
        else:
            print("Reusing timestamp index", flush=True)
        sampler = indexes[key]
        sampler.cancel_event = None
        sampler.fallback_count = 0
        return sampler

    runner.XCLIPClassifier, runner.IndexedTemporalSampler = cached_model, cached_index
    try:
        yield
    finally:
        runner.XCLIPClassifier, runner.IndexedTemporalSampler = original_model, original_index
        models.clear()
        indexes.clear()


def preserved_fingerprints(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("BEGIN")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise RuntimeError("Database integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Database foreign-key check failed")
        result = {}
        for table in PRESERVED_TABLES:
            digest = hashlib.sha256()
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1"):
                digest.update(canonical_json(row).encode("utf-8"))
                digest.update(b"\n")
            result[table] = digest.hexdigest()
        return result
    finally:
        connection.close()


def code_signature(root):
    paths = ("backend/activity_pipeline", "backend/activity_classification",
             "backend/video_retrieval", "backend/analysis_db", "backend/db/schema.sql",
             "backend/scripts/run_activity_checkpoints.py")
    return tuple(git(root, "rev-parse", f"HEAD:{path}") for path in paths)


def run_loop(worktree, main_root, *, chunk_size=500, device="cuda", report_dir=None):
    worktree, main_root = Path(worktree).resolve(), Path(main_root).resolve()
    db = worktree / TRACKED_DB
    report_dir = Path(report_dir or worktree / "backend/results/checkpoints")
    report_dir.mkdir(parents=True, exist_ok=True)
    baseline = preserved_fingerprints(db)
    signature = code_signature(worktree)
    synchronize_main(worktree, main_root)
    if code_signature(worktree) != signature or preserved_fingerprints(db) != baseline:
        raise RuntimeError("Source code or non-Activity data changed during startup; restart required")
    number = 1
    while (report_dir / f"batch_{number:04d}.json").exists():
        number += 1
    with reuse_runtime():
        while True:
            if code_signature(worktree) != signature:
                raise RuntimeError("Inference code changed; restart before processing more frames")
            report_path = report_dir / f"batch_{number:04d}.json"
            print(f"START checkpoint {number:04d}: up to {chunk_size} pending instances", flush=True)
            try:
                summary = runner.run_activity(
                    db, sample_size=None, limit=chunk_size, device=device,
                    precision="fp32", batch_size=2, prefetch_batches=2,
                )
            except KeyboardInterrupt as exc:
                if getattr(exc, "report", None):
                    report_path.write_text(canonical_json(exc.report) + "\n", encoding="utf-8")
                print("Stopped. Completed rows are saved locally; partial chunk was not published.", flush=True)
                raise
            report_path.write_text(canonical_json(summary.report) + "\n", encoding="utf-8")
            if summary.failed:
                raise RuntimeError(f"Chunk has {summary.failed} failed instances; saved locally for inspection")
            if not summary.written:
                if preserved_fingerprints(db) != baseline:
                    raise RuntimeError("Non-Activity tables changed before final publication")
                reconcile_publication(worktree, main_root)
                print("COMPLETE: no pending instances remain; final checkpoint is published", flush=True)
                return
            if preserved_fingerprints(db) != baseline:
                raise RuntimeError("Non-Activity tables changed; checkpoint was not published")
            configuration = summary.report["configuration"]
            config_hash = config_fingerprint(configuration)
            connection = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
            try:
                total = connection.execute("SELECT COUNT(*) FROM Activity").fetchone()[0]
                current = connection.execute(
                    "SELECT COUNT(*) FROM Activity WHERE config_hash=?", (config_hash,)
                ).fetchone()[0]
                cutoff = configuration["decision_policy"]["min_score_exclusive"]
                fallback = configuration["decision_policy"]["uncertain_label"]
                invalid = connection.execute(
                    "SELECT COUNT(*) FROM Activity WHERE config_hash=? AND activity_label != "
                    "CASE WHEN score > ? THEN json_extract(result_json,'$.predictions[0].label') ELSE ? END",
                    (config_hash, cutoff, fallback),
                ).fetchone()[0]
                if invalid:
                    raise RuntimeError("Stored activity decisions do not match the configured cutoff")
            finally:
                connection.close()
            commit = publish_checkpoint(
                worktree, main_root,
                f"data: checkpoint activity batch {number:04d} ({summary.written} instances)",
            )
            if preserved_fingerprints(main_root / TRACKED_DB) != baseline:
                raise RuntimeError("Published non-Activity tables differ from the source snapshot")
            print(f"PUBLISHED checkpoint {number:04d}: commit={commit} processed={summary.written} "
                  f"activity_rows={total} current_config_rows={current} "
                  f"remaining={summary.report['remaining_frames']}", flush=True)
            if code_signature(worktree) != signature:
                raise RuntimeError("Merged inference code changed; restart the process before continuing")
            if not summary.report["remaining_frames"]:
                print("COMPLETE: all eligible instances processed and pushed", flush=True)
                return
            number += 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-root", required=True, type=Path)
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args(argv)
    if args.chunk_size <= 0:
        parser.error("--chunk-size must be positive")
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        run_loop(REPOSITORY_ROOT, args.main_root, chunk_size=args.chunk_size,
                 device=args.device, report_dir=args.report_dir)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"STOPPED: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
