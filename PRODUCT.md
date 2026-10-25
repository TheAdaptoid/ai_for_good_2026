# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

TPA program staff at The Performance Academy (Jacksonville, FL) review footage of their own youth
programs, such as the THIS IS ME camp, final shows, songwriting sessions, and promos. They work on a
laptop, often in long review sessions. Their job is to find meaningful moments: who participated,
in what activity, with what visible engagement. They confirm or correct machine suggestions so the
program has a trustworthy record. (Confirmed 2026-10-25.)

The participants on screen are mostly teens (about 14–19), many in out-of-home care or
justice-involved. They are never users of this app and appear only as anonymous IDs
(`Person_0001`).

## Product Purpose

Turn long, local program footage into searchable, reviewable timelines of activities,
participation, and visible-affect observations. Machines suggest; staff decide. Success means staff
can open a video, see who is on screen and the suggested moments, review them quickly, and export
an authoritative record without any footage leaving the machine.

## Positioning

A local-only, privacy-first review tool built for one youth arts nonprofit's own footage. It keeps
anonymous cross-video participant timelines with no identity discovery, shows human authority over
every AI suggestion (source and review status kept separate), and keeps an append-only review
history. Cloud video-AI products cannot truthfully offer local processing of sensitive minors'
footage.

## Operating Context

- Runs on a staff laptop: FastAPI service plus React app, SQLite, and videos in `data/videos/`.
  Nothing is uploaded.
- Core workflow: sign in → dashboard / review queue → video with timeline (review clips, scene
  row, one row per participant) → review panel (Accept / Edit / Reject / Defer / Create) →
  participant view across videos → CSV/JSON export.
- Data today: 12 videos (9 s to 1 h 50 min), 100 anonymous participants, 50,514 face detections.
  Generated review clips and AI annotations come from the local generation pipeline.
- Also shown in the AI for Good 2026 hackathon demo, but staff use is primary.

## Capabilities and Constraints

- Terminology: review clip, annotation, activity label, observation label, "Visible
  Positive/Neutral/Negative Affect" (observable signals, never emotional states), source (AI/HUMAN),
  review status (UNREVIEWED/ACCEPTED/EDITED/REJECTED/DEFERRED), review priority (a ranking
  heuristic, never a percentage or confidence), model confidence.
- Model confidence, review priority, and human decisions are always displayed separately.
  Unreviewed AI suggestions must look visibly different from human-reviewed values.
- Real participant footage must never be shown to cloud tools. Screenshots mask the video element.
- No external resources at runtime (fonts must be self-hosted or system), fully offline.
- Constitution: `.specify/memory/constitution.md`. Decisions: `docs/DECISIONS.md`.

## Brand Commitments

The Performance Academy ("TPA"; headings render "THE PERFORMANCE ACADEMY"). There is no formal
brand guide. The user designated the public website https://jaxtpa.org/ as the brand source.
Observed there on 2026-10-25 (WordPress/Elementor CSS):

- colors: dark ink `#201C25` / `#1B252F`; magenta-pink `#E2498A`, `#CF005C`, `#C21866`; purple
  `#7851B9`, `#631DA8`, `#D600FF`, `#C77BFF`; orange `#F25E0D`; coral `#FF4255`; warm off-whites
  `#F8F7F8`, `#F1F1EB`; gray `#6F717A`
- type: Archivo (most used), Montserrat (bold uppercase labels), Nunito (theme)
- tagline: "Helping the youth in Jacksonville discover healing through the arts and real-world
  life skills."
- voice: warm, hopeful, empowering; short emphatic phrases

No logo file is in the repository. Do not recreate or approximate the TPA logo.

## Evidence on Hand

Real videos and analysis data are local only (`data/`, git-ignored except the derived SQLite seed).
There are no testimonials, metrics, or evaluation results. Do not fabricate model accuracy or
outcome claims.

## Product Principles

1. Humans decide, machines suggest. AI output always reads as a suggestion awaiting review.
2. Dignity and privacy of young participants first: anonymous IDs, observable-signal language, no
   footage leaves the machine.
3. Review efficiency over decoration. Long sessions demand calm, scannable, consistent UI.
4. Honest uncertainty: confidence, priority, and human judgment are never conflated.

## Accessibility & Inclusion

WCAG 2.2 AA (confirmed 2026-10-25): AA contrast, keyboard reachability with visible focus, and
review state readable without relying on color alone.
