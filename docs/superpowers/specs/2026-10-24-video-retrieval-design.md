# Video retrieval design

Date: 2026-10-24. User approved PyAV and requested parallel execution for a hackathon.

## Scope and architecture

Implement `backend/video_retrieval/{__init__,contracts,retrieval}.py`, synthetic
pytest coverage, and an output-cleared validation notebook. No inference, image
exports, persistent caching, or database record changes.

Reuse `analysis_db.paths.DEFAULT_DB` and `REPOSITORY_ROOT`. Add an optional
`read_only=False` argument to `analysis_db.storage.connect_database`; true selects
SQLite URI `mode=ro`, retaining existing foreign-key setup and other defaults.
Retriever operations open short-lived read-only connections and always close them.

Expose `VideoRetriever(db_path: str | Path | None = None)` with a resolved
`db_path: Path` property and `get_frame(video_id, frame_number)`,
`get_face(detection_id)`, `get_clip(detection_id)`, and
`get_detection_info(detection_id)`. Images are RGB uint8 arrays.
`DetectionInfo` is a frozen dataclass with integer detection/video IDs, string
person/frame IDs, integer frame number, float source timestamp, and a four-float
`bbox` tuple. Missing records raise LookupError; missing files raise
FileNotFoundError; invalid frame numbers and crops raise ValueError; decoder
failures raise a contextual RuntimeError.

Decode the first video stream sequentially in presentation order with PyAV.
Never use approximate seeking or duration-times-fps to establish indices or EOF.
Convert only requested frames to RGB arrays. A clip uses one decoder operation,
collects the window f-16 through f+15, and repeats actual first/last frames at
boundaries. The detection reference frame must exist; EOF before that frame is
an error. Close the container even on failures. Late requests in long videos
have linear decoding latency; this is the approved correctness-first trade-off.

Crop lower coordinates with floor and upper coordinates with ceil, clamp all
coordinates to image dimensions, and reject nonfinite or empty bounds. Do not
resize. Clips contain exactly 32 chronological full frames.

## Validation

Synthetic videos use distinctive spatial/color patterns with known frame indices
and temporary databases initialized from the existing schema. Cover all requested
frame/crop/clip/error cases plus fractional boxes, missing files, read-only access,
resource release, and a long-GOP H.264 case if the encoder is available.
The standard test suite never accesses production data.

The notebook imports retrieval methods; only discovery/diagnostic SQL lives there.
Use seed 42, show database counts and typed detection metadata, draw the box and
person ID, show crop size, and build a 4x8 contact sheet with reference slot 16
highlighted. Label source indices and distinguish repetition. Boundary checks
compare returned images to get_frame and report when true edge detections are
absent rather than claiming coverage. Keep only one full clip in memory at a time.
Run notebook cells locally with outputs retained only in memory, then store the
notebook with null execution counts and empty outputs.

Source CSV frame 0 has timestamp 0; the sampled original begins at PTS zero with
24000/1001 frame rate. Validate more source frames against sequential decoding and
timestamps during integration without exporting any images.

## Work ownership

1. Core worker: `video_retrieval/` only.
2. Test worker: `tests/test_video_retrieval.py` only.
3. Notebook worker: `notebooks/video_retrieval_validation.ipynb` only.
4. Coordinator: connection helper, dependencies/lock, README, integration checks.

Workers share the API above and edit disjoint files. No commits are requested.
