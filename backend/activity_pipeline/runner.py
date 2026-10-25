"""Seeded, resumable activity processing with bounded CPU/GPU overlap."""

from collections import Counter
from contextlib import closing
from dataclasses import dataclass, fields
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread
from time import perf_counter

import numpy as np

from activity_classification import XCLIPClassifier
from activity_classification.classifier import prepare_candidates
from activity_classification.runtime import MODEL_ID, MODEL_REVISION
from analysis_db.activity_results import (
    canonical_json, config_fingerprint, input_fingerprint, input_metadata,
    result_matches, save_activity,
)
from analysis_db.activity_schema import require_activity_schema
from analysis_db.paths import REPOSITORY_ROOT
from analysis_db.storage import connect_database
from video_retrieval.indexed import IndexedTemporalSampler, SAMPLER_VERSION
from .config import (ACTIVITIES, ACTIVITY_DESCRIPTIONS, BATCH_SIZE, BENCHMARK_SIZE,
                     INTERVAL_SECONDS, MIN_ACTIVITY_SCORE, PRECISION, PREFETCH_BATCHES,
                     SAMPLE_COUNT, SEED, UNCERTAIN_LABEL)
from .selection import sample_frame_jobs, select_frame_jobs


@dataclass(frozen=True)
class RunSummary:
    population: int
    selected: int
    skipped: int
    attempted: int
    written: int
    failed: int
    report: dict


def _is_oom(exc):
    import torch
    while exc is not None:
        if isinstance(exc, torch.OutOfMemoryError):
            return True
        exc = exc.__cause__
    return False


def run_activity(db_path: Path, *, video_ids=(), sample_size=BENCHMARK_SIZE, seed=SEED,
                 limit=None, device="auto", precision=PRECISION, batch_size=BATCH_SIZE,
                 prefetch_batches=PREFETCH_BATCHES, dry_run=False):
    for name, value in (("limit",limit),("batch_size",batch_size),("prefetch_batches",prefetch_batches)):
        if value is not None and (isinstance(value,bool) or not isinstance(value,int) or value <= 0):
            raise ValueError(f"{name} must be a positive integer")
    if precision not in ("fp32", "fp16"):
        raise ValueError("precision must be fp32 or fp16")
    with closing(connect_database(db_path, must_exist=True, read_only=dry_run)) as connection:
        report = {}
        try:
            return _run(connection, video_ids, sample_size, seed, limit, device, precision,
                        batch_size, prefetch_batches, dry_run, report)
        except KeyboardInterrupt as exc:
            report.update(interrupted=True,timing_sample="partial",remaining_frames=None,
                          estimated_remaining_seconds=None)
            report["setup_total_seconds"]=sum(report.get("setup_seconds",{}).values())
            if report.get("written") and report.get("processing_wall_seconds"):
                report["seconds_per_frame"]=report["processing_wall_seconds"]/report["written"]
            exc.report=report
            raise


def _run(connection, video_ids, sample_size, seed, limit, device, precision,
         batch_size, prefetch_batches, dry_run, report):
    selection_start = perf_counter()
    population = select_frame_jobs(connection,video_ids=video_ids)
    selected = sample_frame_jobs(population,sample_size=sample_size,seed=seed)
    paths = {v: REPOSITORY_ROOT / Path(p) for v,p in connection.execute("SELECT video_id,file_path FROM Video")}
    stats = {v:paths[v].stat() for v in {j.video_id for j in population}}
    metadata = [input_metadata(j,video_path=paths[j.video_id],repository_root=REPOSITORY_ROOT,
                               stat=stats[j.video_id]) for j in population]
    hashes = {j.frame_id:config_fingerprint(m) for j,m in zip(population,metadata)}
    report.update({
        "population":len(population),"selected":len(selected),"seed":seed,"sample_size":sample_size,
        "selected_frame_ids":[j.frame_id for j in selected],
        "population_fingerprint":config_fingerprint(metadata),
        "per_video_selected":dict(Counter(j.video_id for j in selected)),
        "unrepresented_video_ids":sorted({j.video_id for j in population}-{j.video_id for j in selected}),
        "settings":{"interval_seconds":INTERVAL_SECONDS,"sample_count":SAMPLE_COUNT,
                    "batch_size":batch_size,"precision":precision,"prefetch_batches":prefetch_batches,
                    "requested_device":device,"sampler_version":SAMPLER_VERSION},
        "setup_seconds":{"selection":perf_counter()-selection_start},
        "processing_wall_seconds":0.0,"inference_batches":0,"batch_sizes":[],
        "phase_seconds":{"retrieval":0.0,"preparation":0.0,"inference":0.0,"write":0.0},
        "batch_timings":[],"per_frame_timings":[],"failures":[],
        "seconds_per_frame":None,"remaining_frames":len(population),
        "estimated_remaining_seconds":None,"timing_sample":"none",
        "peak_gpu_memory_allocated_mib":None,"seek_fallbacks":0,
    })
    descriptions = {label: ACTIVITY_DESCRIPTIONS[label] for label in ACTIVITIES}
    report["settings"].update(
        activities=list(ACTIVITIES),
        prompts=[c.prompt for c in prepare_candidates(list(ACTIVITIES), descriptions=descriptions)],
        decision_policy={"min_score_exclusive":MIN_ACTIVITY_SCORE,"uncertain_label":UNCERTAIN_LABEL},
    )
    skipped = attempted = written = failed = 0
    if dry_run or not selected:
        return RunSummary(len(population),len(selected),0,0,0,0,report)
    require_activity_schema(connection)
    import torch
    resolved_device = (torch.device("cuda", torch.cuda.current_device())
                       if device == "auto" and torch.cuda.is_available() else
                       torch.device("cpu" if device == "auto" else device))
    if resolved_device.type == "cuda" and resolved_device.index is None:
        resolved_device = torch.device("cuda", torch.cuda.current_device())
    if precision == "fp16" and resolved_device.type != "cuda":
        raise ValueError("FP16 precision requires CUDA")
    dtype = torch.float32 if precision == "fp32" else torch.float16
    settings = dict(report["settings"])
    # Queue depth and center selection do not change a clip's intended model input.
    settings.pop("prefetch_batches")
    settings.pop("requested_device")
    settings.update(model=MODEL_ID,model_revision=MODEL_REVISION,device=str(resolved_device),dtype=str(dtype))
    config_json, config_hash = canonical_json(settings), config_fingerprint(settings)
    report["configuration"] = settings
    pending = []
    for job in selected:
        if result_matches(connection,job.frame_id,config_hash,hashes[job.frame_id]):
            skipped += 1
        else:
            pending.append(job)
    if limit is not None:
        pending = pending[:limit]
    classifier = None
    if pending:
        started = perf_counter()
        classifier = XCLIPClassifier(device=device,precision=precision)
        report["setup_seconds"]["model_load"] = perf_counter()-started
    samplers = {}
    for video_id in sorted({j.video_id for j in pending}):
        print(f"Indexing video {video_id}...",flush=True)
        started=perf_counter()
        samplers[video_id]=IndexedTemporalSampler(paths[video_id])
        report["setup_seconds"][f"index_video_{video_id}"]=perf_counter()-started
        print(f"Indexed video {video_id}: {len(samplers[video_id].times):,} frames in "
              f"{report['setup_seconds'][f'index_video_{video_id}']:.1f}s",flush=True)
    if pending:
        started=perf_counter()
        dummy=np.zeros((SAMPLE_COUNT,classifier.image_size,classifier.image_size,3),np.uint8)
        classifier.classify_batch([dummy]*batch_size,list(ACTIVITIES),descriptions=descriptions)
        report["setup_seconds"]["warmup"]=perf_counter()-started
        del dummy
    queue=Queue(maxsize=prefetch_batches)
    stop=Event()
    for sampler in samplers.values():
        sampler.cancel_event=stop

    def put(item):
        while not stop.is_set():
            try:
                queue.put(item,timeout=0.1)
                return
            except Full:
                pass

    def producer():
        jobs, clips, sampling = [], [], []
        try:
            def emit():
                if not jobs:
                    return
                try:
                    prepared=classifier.prepare_batch(clips,list(ACTIVITIES),descriptions=descriptions)
                    item=("batch",tuple(jobs),tuple(sampling),prepared)
                except Exception as exc:
                    # Isolate a bad preparation input without discarding its valid peer.
                    for job,clip,meta in zip(jobs,clips,sampling):
                        try:
                            prepared=classifier.prepare_batch([clip],list(ACTIVITIES),descriptions=descriptions)
                            put(("batch",(job,),(meta,),prepared))
                        except Exception as single:
                            put(("clip_error",job,str(single)))
                    return
                finally:
                    clips.clear()
                put(item)
            for job in pending:
                if stop.is_set():
                    break
                started=perf_counter()
                try:
                    clip=samplers[job.video_id].sample(reference_frame_number=job.frame_number,
                                                       center_seconds=job.source_time_seconds,
                                                       interval_seconds=INTERVAL_SECONDS,sample_count=SAMPLE_COUNT)
                    meta={f.name:getattr(clip,f.name) for f in fields(clip) if f.name!="frames"}
                    meta.update(unique_frame_count=clip.unique_frame_count,
                                retrieval_time_seconds=perf_counter()-started)
                    jobs.append(job)
                    clips.append(clip.frames)
                    sampling.append(meta)
                    del clip
                except Exception as exc:
                    put(("clip_error",job,str(exc)))
                    continue
                if len(jobs)==batch_size:
                    emit()
                    jobs.clear(); sampling.clear()
            if not stop.is_set():
                emit()
        except BaseException as exc:
            put(("fatal",exc))
        finally:
            clips.clear()
            put(("done",))

    processing_start=perf_counter()
    worker=Thread(target=producer,name="activity-preparation",daemon=True)
    if pending:
        worker.start()
    try:
        while pending:
            try:
                item=queue.get(timeout=0.2)
            except Empty:
                if not worker.is_alive():
                    raise RuntimeError("Preparation worker stopped without completion")
                continue
            if item[0]=="done":
                break
            if item[0]=="fatal":
                raise item[1]
            if item[0]=="clip_error":
                _,job,message=item
                attempted+=1; failed+=1
                report["failures"].append({"frame_id":job.frame_id,"video_id":job.video_id,"error":message})
                print(f"Failed frame {job.frame_id}: {message}",flush=True)
                continue
            _,jobs,metas,prepared=item
            attempted+=len(jobs)
            started=perf_counter()
            try:
                results=classifier.classify_prepared_batch(prepared)
            except Exception as exc:
                if _is_oom(exc):
                    raise
                failed+=len(jobs)
                report["failures"].extend({"frame_id":j.frame_id,"video_id":j.video_id,"error":str(exc)} for j in jobs)
                continue
            inference_seconds=perf_counter()-started
            if len(results)!=len(jobs):
                raise RuntimeError("Classifier did not return one result per input clip")
            report["inference_batches"]+=1
            report["batch_sizes"].append(len(jobs))
            report["batch_timings"].append({"size":len(jobs),"preparation_seconds":prepared.preprocessing_time_seconds,
                                            "inference_seconds":inference_seconds})
            report["phase_seconds"]["preparation"]+=prepared.preprocessing_time_seconds
            report["phase_seconds"]["inference"]+=inference_seconds
            for job,meta,result in zip(jobs,metas,results):
                if input_fingerprint(job,video_path=paths[job.video_id],repository_root=REPOSITORY_ROOT)!=hashes[job.frame_id]:
                    raise RuntimeError("Source input changed during processing")
                meta["actual_batch_size"]=len(jobs)
                started=perf_counter()
                save_activity(connection,job,meta,result,config_json=config_json,config_hash=config_hash,
                              input_hash=hashes[job.frame_id],retrieval_time_seconds=meta["retrieval_time_seconds"])
                write_seconds=perf_counter()-started
                written+=1
                report["phase_seconds"]["write"]+=write_seconds
                report["phase_seconds"]["retrieval"]+=meta["retrieval_time_seconds"]
                report["per_frame_timings"].append({"frame_id":job.frame_id,"video_id":job.video_id,
                                                    "retrieval_seconds":meta["retrieval_time_seconds"],
                                                    "write_seconds":write_seconds})
                if result.peak_gpu_memory_allocated_mib is not None:
                    report["peak_gpu_memory_allocated_mib"]=max(report["peak_gpu_memory_allocated_mib"] or 0,
                                                               result.peak_gpu_memory_allocated_mib)
            print(f"Completed {written}/{len(pending)} pending frames "
                  f"(batch {len(jobs)}, GPU stage {inference_seconds:.2f}s)",flush=True)
            del item,prepared,results
    finally:
        stop.set()
        if pending:
            worker.join()
        report["processing_wall_seconds"]=perf_counter()-processing_start if pending else 0.0
        report.update(skipped=skipped,attempted=attempted,written=written,failed=failed)
    report["seek_fallbacks"]=sum(s.fallback_count for s in samplers.values())
    report["remaining_frames"]=sum(not result_matches(connection,j.frame_id,config_hash,hashes[j.frame_id]) for j in population)
    if written:
        report["seconds_per_frame"]=report["processing_wall_seconds"]/written
        report["estimated_remaining_seconds"]=report["remaining_frames"]*report["seconds_per_frame"]
        report["timing_sample"]=("complete" if sample_size==100 and written==100 and not failed and not skipped else "partial")
    report.update(skipped=skipped,attempted=attempted,written=written,failed=failed,
                  phase_totals_overlap=True,setup_total_seconds=sum(report["setup_seconds"].values()))
    return RunSummary(len(population),len(selected),skipped,attempted,written,failed,report)
