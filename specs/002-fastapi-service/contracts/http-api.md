# HTTP API Contract

The generated OpenAPI schema (`/api/openapi.json`) is authoritative (Constitution X). This table is
the intended surface. All paths are under `/api`. All endpoints require the `tpa_session` cookie
except those marked *public*. Errors use `{"detail": ...}` with 400 (domain validation),
401 (no or invalid session), 404 (not found), and 422 (request shape).

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| GET | `/health` *public* | | `{"status": "ok"}` |
| POST | `/auth/login` *public* | `{username, password}` | `StaffAccount`, sets cookie. 401 on failure |
| POST | `/auth/logout` | | 204, clears cookie |
| GET | `/auth/me` | | `StaffAccount` |
| GET | `/videos` | | `VideoSummary[]` |
| GET | `/videos/{video_id}` | | `VideoSummary` |
| GET | `/videos/{video_id}/participants` | | `VideoParticipant[]` |
| GET | `/videos/{video_id}/stream` | `Range` header | video bytes, 200/206 |
| GET | `/participants` | | `ParticipantSummary[]` |
| GET | `/participants/{person_id}` | | `ParticipantDetail` |
| GET | `/annotations` | `video_id, start_frame, end_frame, person_id, label_id, category, source, review_status, clip_id, include_rejected` | `Annotation[]` |
| GET | `/annotations/{id}` | | `Annotation` |
| GET | `/annotations/{id}/history` | | `ReviewEvent[]` |
| POST | `/annotations` | `{video_id, label_id, start_frame, end_frame, person_id?, clip_id?, note?}` | `ReviewResult` 201 |
| POST | `/annotations/{id}/accept` | `{note?}` | `ReviewResult` |
| POST | `/annotations/{id}/reject` | `{note?}` | `ReviewResult` |
| POST | `/annotations/{id}/defer` | `{note?}` | `ReviewResult` |
| POST | `/annotations/{id}/edit` | `{label_id?, start_frame?, end_frame?, person_id?, note?}`. `person_id: null` clears it, and omitting it leaves it unchanged | `ReviewResult` |
| GET | `/clips` | `video_id, person_id, order=time\|priority` | `ReviewClip[]` |
| GET | `/labels` | `category, include_inactive` | `Label[]` |
| GET | `/exports/annotations` | `format=csv\|json, include_rejected` | attachment |
| GET | `/exports/history` | `format=csv\|json` | attachment |

`ReviewResult` = `{annotation: Annotation, event: ReviewEvent}`. Request bodies reject unknown
fields, so a `reviewer_id` in the body returns 422.
