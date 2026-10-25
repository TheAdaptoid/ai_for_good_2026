"""Generate review clips and AI annotations locally into a Spec 004 import file.

Reads the database read-only and writes only --output. Importing is a separate step:
``scripts/import_pipeline_output.py --input <output>``.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis_db.contracts import DataError  # noqa: E402
from analysis_db.labels import list_labels  # noqa: E402
from analysis_db.paths import DEFAULT_VIDEO_DIR, REPOSITORY_ROOT, WORKING_DB  # noqa: E402
from analysis_db.storage import connect_database  # noqa: E402
from pipeline.builder import build_import_file  # noqa: E402
from pipeline.contracts import PipelineMetadata  # noqa: E402
from pipeline.local_analysis import (  # noqa: E402
    PRIORITY_METHOD, ExpressionAffectAnnotator, GenerationConfig, ParticipantPositivePriority,
    PresenceSegmenter, ZeroShotActivityAnnotator,
)
from pipeline.signals import load_video_signals  # noqa: E402

PIPELINE_NAME = "tpa-local-analysis"
PIPELINE_VERSION = "1.0.0"
PROMPTS_PATH = Path(__file__).resolve().parents[1] / "pipeline" / "activity_prompts.json"


def build_parser() -> argparse.ArgumentParser:
    defaults = GenerationConfig()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", required=True, type=Path, help="import file to write")
    parser.add_argument("--db", type=Path, default=WORKING_DB,
                        help="source database, opened read-only (default: %(default)s)")
    parser.add_argument("--video", action="append", default=[],
                        help="video filename or id (repeatable; default: every video)")
    parser.add_argument("--video-dir", type=Path, default=DEFAULT_VIDEO_DIR,
                        help="only video files inside this directory are read (default: %(default)s)")
    parser.add_argument("--device", choices=("auto", "cuda", "mps", "cpu"), default="auto",
                        help="activity model device; auto picks cuda, then mps, then cpu")
    parser.add_argument("--no-activity", action="store_true",
                        help="skip activity inference (clips, affect, and priority only)")
    parser.add_argument("--generated-at", help="fixed ISO-8601 generation time, for reproducible files")
    for name, value in defaults.parameters().items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=type(value), default=value,
                            help=f"(default: {value})")
    return parser


def resolve_device(choice: str) -> str:
    if choice != "auto":
        return choice
    import torch
    if torch.cuda.is_available():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def select_videos(connection: sqlite3.Connection, requested: list[str]) -> list[tuple[int, str, str]]:
    rows = connection.execute("SELECT video_id, filename, file_path FROM Video ORDER BY video_id").fetchall()
    if not requested:
        return rows
    chosen = []
    for item in requested:
        match = [r for r in rows if str(r[0]) == item or r[1] == item]
        if not match:
            raise DataError(f"unknown video {item!r}")
        chosen += [r for r in match if r not in chosen]
    return chosen


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = GenerationConfig(**{name: getattr(args, name) for name in GenerationConfig().parameters()})
    started = perf_counter()
    try:
        connection = connect_database(args.db, read_only=True)
    except (DataError, OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    temporary = None
    try:
        videos = select_videos(connection, args.video)
        signals = [load_video_signals(connection, video_id) for video_id, _, _ in videos]
        parameters: dict[str, str | int | float | bool | None] = dict(config.parameters())
        parameters.update(priority_method=PRIORITY_METHOD, activity="disabled" if args.no_activity else "enabled")
        models: tuple[tuple[str, str | None], ...] = ()
        activity = []
        annotator = None
        if not args.no_activity:
            labels = [label.name for label in list_labels(connection, category="activity")]
            prompts_text = PROMPTS_PATH.read_text(encoding="utf-8")
            video_dir = args.video_dir.resolve()
            paths, missing = {}, []
            for _, filename, file_path in videos:
                path = (REPOSITORY_ROOT / file_path).resolve()
                if path.is_relative_to(video_dir) and path.is_file():
                    paths[filename] = path
                else:
                    missing.append(filename)
            from activity_classification import XCLIPClassifier
            from activity_classification.runtime import MODEL_ID, MODEL_REVISION
            from pipeline.frames import read_windows
            device = resolve_device(args.device)
            classifier = XCLIPClassifier(device=device)
            annotator = ZeroShotActivityAnnotator(classifier, labels, json.loads(prompts_text), paths,
                                                  read_windows, config)
            activity = [annotator]
            models = ((MODEL_ID, MODEL_REVISION),)
            parameters.update(device=device, activity_labels=";".join(labels),
                              activity_prompts_sha256=hashlib.sha256(prompts_text.encode()).hexdigest(),
                              activity_unavailable=";".join(missing) or None)
            for filename in missing:
                print(f"warning: {filename}: video file unavailable, no activity annotations",
                      file=sys.stderr)
        generated_at = args.generated_at or datetime.now(UTC).isoformat(timespec="seconds")
        info = PipelineMetadata(PIPELINE_NAME, PIPELINE_VERSION, generated_at, models,
                                tuple(sorted(parameters.items())))
        parsed = build_import_file(info, signals, PresenceSegmenter(config), activity=activity,
                                   affect=[ExpressionAffectAnnotator()],
                                   scorer=ParticipantPositivePriority())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the destination, then rename: a failed run never leaves a partial file.
        handle, temporary = tempfile.mkstemp(dir=args.output.parent, prefix=f".{args.output.name}.")
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(parsed.to_json())
        os.replace(temporary, args.output)
        temporary = None
    except (DataError, LookupError, OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"error: nothing written: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.close()
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    clips = sum(len(v.clips) for v in parsed.videos)
    annotations = [a for v in parsed.videos for a in v.annotations]
    print(f"Wrote {args.output} ({args.output.stat().st_size} bytes)")
    print(f"  videos: {len(parsed.videos)}  clips: {clips}  annotations: {len(annotations)}"
          f" (activity {sum(a.label.category == 'activity' for a in annotations)},"
          f" affect {sum(a.label.category == 'observation' for a in annotations)})")
    if annotator is not None:
        print(f"  activity windows: {annotator.windows_classified}  inference: "
              f"{annotator.inference_seconds:.1f}s  decode: {annotator.decode_seconds:.1f}s")
    print(f"  total: {perf_counter() - started:.1f}s")
    print(f"Import with: uv run python scripts/import_pipeline_output.py --input {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
