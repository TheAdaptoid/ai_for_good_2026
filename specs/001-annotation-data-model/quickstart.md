# Quickstart: Validate the Annotation Data Model

Run every command from `backend/`. API details are in
[contracts/python-api.md](contracts/python-api.md), and table rules are in
[data-model.md](data-model.md).

## Prerequisites

```bash
uv sync --locked
```

## 1. Migrate a copy of the real database (US4, SC-001, SC-006)

```bash
cp ../data/analysis.sqlite /tmp/migrate-check.sqlite
sqlite3 /tmp/migrate-check.sqlite "select count(*) from Video; select count(*) from Person; select count(*) from FaceDetection; select count(*) from Engagement"
uv run python scripts/init_db.py --db /tmp/migrate-check.sqlite
uv run python scripts/init_db.py --db /tmp/migrate-check.sqlite   # second run: same counts
```

Expected:
- Counts are unchanged: Video 12, Person 100, FaceDetection 50514, Engagement 50514.
- Label has 18 rows.
- Annotation, ReviewClip, and ReviewEvent each have 0 rows.
- The second run reports identical counts.

```bash
sqlite3 /tmp/migrate-check.sqlite "select * from Engagement where detection_id = 1"
```

Expected: the same three scores as in the original file.

## 2. Automated suite (US1–US8, SC-002–SC-004, SC-007, SC-008)

```bash
uv run pytest -q
```

Expected: all tests pass. The test that migrates the real database skips if
`../data/analysis.sqlite` is absent.

## 3. Manual review walkthrough (US2, US3)

In `uv run python`:

1. Import one clip and one AI annotation ("Singing", confidence 0.6) with
   `import_machine_output`.
2. Call `edit(…, AnnotationChanges(label_id=<Spoken Performance>), reviewer_id="r-1")`.
   Expected: `source == "HUMAN"`, `review_status == "EDITED"`, `confidence is None`.
3. Call `accept(…)`. Expected: source stays HUMAN, and status is ACCEPTED.
4. Call `get_history(…)`. Expected: two events, and the first has `prev_label_id` = Singing and
   `prev_confidence` = 0.6.
5. Re-run the same `import_machine_output`. Expected: `skipped_protected == 1`, and the
   annotation is unchanged.
6. Try `conn.execute("DELETE FROM ReviewEvent")`. Expected: `sqlite3.IntegrityError`, with
   "review history is append-only".

## 4. Export (FR-027)

```bash
uv run python scripts/export_annotations.py --db /tmp/migrate-check.sqlite --format csv --output /tmp/annotations.csv
```

Expected: a header-only CSV, because the migration creates no annotations. It opens in a
spreadsheet tool.
