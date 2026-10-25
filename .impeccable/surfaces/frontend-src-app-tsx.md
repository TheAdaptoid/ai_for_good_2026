---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: ["frontend/src/styles.css"]
---

# Surface brief: TPA Video Review staff app (all screens)

Scope: sign-in, dashboard and review queue, video view (player, timeline, clip and review panels), participant view. Mode: Operate.
Audience and job: TPA program staff in long laptop review sessions confirming or correcting AI suggestions about anonymous participants.
Constraints: WCAG 2.2 AA; no footage in any artifact; fonts self-hosted (offline); source and review status, confidence, and priority always separate; avoid surveillance, gamified, generic-SaaS, and marketing-site feels.
Memorable moment: the timeline reads as the evening's program, with a scene listing and a cast list of anonymous participants.

## Direction contract

THESIS: Each video is a showcase night's printed program. The masthead, cover line, scene listing (review clips), and cast list (participant rows with dot leaders and running times) organize review. It refuses the gray SaaS sidebar-and-inspector template.

OWN-WORLD: TPA ink #201C25 masthead with a 4px magenta #C21866 rule, a #F8F7F8 ground, and white program panels split by hairlines (no shadows). Montserrat 700–800 wide caps for the masthead, titles, and section labels; Archivo for body and tabular data. Purple #631DA8 means activity, magenta #C21866 means observation, and orange #F25E0D means only "awaiting review" (dashed). Times sit right-aligned in full ink.

STORY: Staff see what is on tonight (dashboard program), open a video, read the scenes and cast, and review each suggestion. Human decisions read as solid, AI suggestions as dashed orange.

FIRST VIEWPORT: Ink masthead with nav at left and user at right. The cover band holds a kicker, the Montserrat title, a meta line, and Add annotation at right. On the left: player, then the timeline with running-time, scenes, whole-scene, and cast rows. On the right: a 380px review panel with Accept/Edit/Defer, and Reject apart.

FORM: Theater Program, my candidate 3 of 7 (assigned); seed:00a6dd9359b49bba. Raises: Reject isolated and hairlines (console); one body size (acetate); focus row lifts, others dim (streaming); orange means awaiting review only (airport); right-aligned tabular times (j-card); full-ink numbers (datamatics).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
