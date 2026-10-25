# Import File Format `tpa-review-import/1`

JSON, UTF-8. Validated in full before anything is stored. One file is one all-or-nothing import.

```json
{
  "format": "tpa-review-import/1",
  "pipeline": {
    "name": "clip-pipeline",
    "version": "1.0.0",
    "generated_at": "2026-10-25T12:00:00Z",
    "models": [{"name": "microsoft/xclip-base-patch16-zero-shot", "revision": "6746d6a…"}]
  },
  "videos": [
    {
      "filename": "this is me-songwriting-camp2-reese.mp4",
      "clips": [
        {"key": "clip-pipeline:clip:3f…", "start_frame": 0, "end_frame": 239,
         "participants": ["Person_0001"],
         "priority": {"score": 1.37, "method": "positive-affect-per-participant@1"}}
      ],
      "annotations": [
        {"key": "clip-pipeline:annotation:9a…", "clip_key": "clip-pipeline:clip:3f…",
         "label": {"name": "Singing", "category": "activity"}, "confidence": 0.71},
        {"key": "clip-pipeline:annotation:b2…", "clip_key": "clip-pipeline:clip:3f…",
         "person_id": "Person_0001", "start_frame": 0, "end_frame": 239,
         "label": {"name": "Visible Positive Affect", "category": "observation"}, "confidence": 0.64}
      ]
    }
  ]
}
```

| Field | Rule |
|---|---|
| `format` | exactly `tpa-review-import/1` |
| `pipeline.name`, `version` | non-empty |
| `pipeline.models` | list, may be empty. Each entry has a non-empty `name`; `revision` is optional |
| `videos[].filename` | must match an existing `Video.filename`, and each filename may appear only once |
| `clips[].key` | non-empty, unique within the file |
| `clips[].start_frame/end_frame` | integers, `0 ≤ start ≤ end < frame count` |
| `clips[].participants` | existing participant IDs, may be empty, no duplicates |
| `clips[].priority` | optional. `score ≥ 0` (no upper bound), `method` non-empty. It is a review-priority ranking, **not** a confidence or probability |
| `annotations[].key` | non-empty, unique within the file |
| `annotations[].label` | `{name, category}` resolving to an existing label. Inactive labels are refused unless the row is protected |
| `annotations[].start_frame/end_frame` | required unless `clip_key` is given and `person_id` is absent, in which case they default to the clip span |
| `annotations[].person_id` | optional existing participant. Absent or null means scene-level or clip-level |
| `annotations[].clip_key` | optional. Must name a clip in the same video entry or an existing clip of that video |
| `annotations[].confidence` | optional, `0 ≤ c ≤ 1`, the model's certainty in its prediction |

Unknown fields are refused. Stored annotations get `source = AI`, `review_status = UNREVIEWED`.
Protection, upsert, and no-delete rules are Spec 001 FR-019/FR-034.
