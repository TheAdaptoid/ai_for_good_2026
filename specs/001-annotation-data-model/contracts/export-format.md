# Contract: Export Formats (FR-027, FR-028)

CSV files are UTF-8 with a header row, in the column order below. JSON files are a top-level array
of objects using the same keys. Empty or NULL values are an empty CSV cell, or `null` in JSON.
Rejected annotations are excluded unless `--include-rejected` is passed.

## Annotations

| Column | Example |
|---|---|
| `annotation_id` | `42` |
| `video_id` | `3` |
| `clip_id` | `17` |
| `person_id` | `Person_0007` |
| `label_id` | `1` |
| `label_name` | `Singing` |
| `label_category` | `activity` |
| `start_frame` | `17600` |
| `end_frame` | `18415` |
| `start_seconds` | `734.067` |
| `end_seconds` | `768.059` |
| `confidence` | `0.62` |
| `source` | `AI` |
| `review_status` | `UNREVIEWED` |
| `updated_at` | `2026-10-24T18:03:11Z` |

Seconds are rounded to 3 decimal places. Exports don't include the review-priority score. It
belongs to clips and is never mixed into annotation rows (FR-031).

## Review history

The columns are `event_id`, `annotation_id`, `video_id`, `action`, `prev_label_id`,
`new_label_id`, `prev_start_frame`, `prev_end_frame`, `new_start_frame`, `new_end_frame`,
`prev_person_id`, `new_person_id`, `prev_confidence`, `new_confidence`, `prev_source`,
`new_source`, `prev_status`, `new_status`, `reviewer_id`, `note`, and `created_at`, ordered by
`event_id`.
