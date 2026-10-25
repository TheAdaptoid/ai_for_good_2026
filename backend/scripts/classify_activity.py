import argparse
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from activity_pipeline.runner import run_activity
from analysis_db.activity_results import canonical_json
from analysis_db.contracts import DataError
from analysis_db.paths import DEFAULT_DB


def positive(value):
    number=int(value)
    if number<=0:
        raise argparse.ArgumentTypeError("Value must be positive")
    return number


def main(argv=None):
    parser=argparse.ArgumentParser(description="Benchmark or resume frame-linked local X-CLIP inference.")
    parser.add_argument("--db",type=Path,default=DEFAULT_DB.with_name("analysis.local.sqlite"))
    parser.add_argument("--video-id",type=int,action="append",default=[])
    selection=parser.add_mutually_exclusive_group()
    selection.add_argument("--sample-size",type=positive,default=100)
    selection.add_argument("--all",action="store_true")
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--limit",type=positive)
    parser.add_argument("--device",default="auto")
    parser.add_argument("--precision",choices=("fp32","fp16"),default="fp32")
    parser.add_argument("--batch-size",type=positive,default=2)
    parser.add_argument("--prefetch-batches",type=positive,default=2)
    parser.add_argument("--dry-run",action="store_true")
    parser.add_argument("--report",type=Path)
    args=parser.parse_args(argv)
    try:
        summary=run_activity(args.db,video_ids=tuple(args.video_id),
                             sample_size=None if args.all else args.sample_size,seed=args.seed,
                             limit=args.limit,device=args.device,precision=args.precision,
                             batch_size=args.batch_size,prefetch_batches=args.prefetch_batches,dry_run=args.dry_run)
        r=summary.report
        print(f"Population={summary.population} selected={summary.selected} skipped={summary.skipped} "
              f"attempted={summary.attempted} written={summary.written} failed={summary.failed}")
        print(f"Per-video selection: {r['per_video_selected']}")
        print(f"Setup: {r.get('setup_total_seconds',0):.2f}s; processing: {r['processing_wall_seconds']:.2f}s")
        if r["seconds_per_frame"] is not None:
            print(f"Rate: {r['seconds_per_frame']:.3f}s/frame; remaining: {r['remaining_frames']:,} frames; "
                  f"estimate: {r['estimated_remaining_seconds']/3600:.2f}h, excluding future setup")
            print(f"Timing sample: {r['timing_sample']}; videos not sampled: {r['unrepresented_video_ids']}")
        if args.report and not args.dry_run:
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(canonical_json(r)+"\n",encoding="utf-8")
            print(f"Report: {args.report}")
        return 1 if summary.failed else 0
    except KeyboardInterrupt as exc:
        if args.report and getattr(exc,"report",None):
            args.report.parent.mkdir(parents=True,exist_ok=True)
            args.report.write_text(canonical_json(exc.report)+"\n",encoding="utf-8")
        print("Interrupted; completed results are saved.",file=sys.stderr)
        return 130
    except (DataError,OSError,sqlite3.Error,ValueError,RuntimeError) as exc:
        print(f"error: {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
