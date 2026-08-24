# FireRuleX — Building-Plan Reading & Equipment-Placement Layer

## Original problem statement
Around an EXISTING, WORKING NBC Part 4 fire-safety compliance engine (must NOT be
modified), build a NEW LAYER that: (Part 1) reads uploaded building plans (PDF/DWG),
recognises Indian sanctioned-plan Table Type 1 (Plot/Built-up/FSI), Type 2
(Occupancy/Area Statement), Type 3 (ODPS approval metadata); maps values to the
existing Manual Entry form fields with confidence indicators + mandatory user review
before use; (Part 2) env-var config with startup status logging, zero-cost by default;
(Part 3) extends the report with Suggested Equipment Quantities (source-labelled) and
a Plan Reference panel; (Part 4) shows Suggested Equipment Placement on the plan
(extinguishers/hose reels as points + schematic riser+ring pipe) only for uploaded
plans with usable vector geometry, with per-block scale calibration, dual-source
validation, unit inference, column-label exclusion, and honest fallback.

## Tech stack (existing, unchanged)
- Frontend: Next.js 16 (App Router) + React 19 + Tailwind v4 + TS, port 3000.
- Backend: FastAPI, supervisor port 8001. Frontend↔backend via Next proxy
  `src/app/api/[...path]/route.ts`.
- Engine (READ-ONLY to new layer): `rule_engine.py`, `engines/`, `*_checker.py`,
  `models.py`. Confirmed byte-identical to HEAD (git diff empty).

## Architecture — new layer (separate module)
- `backend/plan_reader/`: config, pdf_extractor (PyMuPDF), table_parser (Type 1/2/3),
  scale_detector (per-block scale + unit + column exclusion), field_mapper,
  equipment_estimator (Part 3), placement (Part 4), ocr (optional AI, off by default),
  store (in-memory).
- `backend/routes/plan.py`: POST /api/plan/extract, POST /api/plan/placement,
  GET /api/plan/status.
- Frontend: `app/upload/page.tsx` (upload→review→confirm), `components/PlanViewer.tsx`
  (anchored SVG overlay + zoom/pan), `components/PlanSections.tsx` (report additions).
- Entry-mode choice on home: Manual Entry (/manual, unchanged) vs Upload Plan (/upload).

## Technical choices & reasoning
- Core extraction = **PyMuPDF only** (already installed) → zero cost, no external calls;
  covers text+coords, `get_drawings()` vector geometry, `find_tables()`, page render.
- Table detection = deterministic regex/keywords (free, predictable). Type 3 is
  reference-only, never fed to the engine.
- Optional AI-vision OCR (Gemini `gemini-3-flash-preview` via emergentintegrations)
  only for purely scanned sheets; gated by `PLAN_ENABLE_AI_OCR` + `EMERGENT_LLM_KEY`.
- DWG = binary CAD needing external converter (not bundled) → detect + honest fallback.
- Placement runs in real-world metres using block-calibrated scale, then converts back
  to rendered-image pixel space; overlay shares the viewer transform so markers stay
  anchored. Spacing is READ from the engine's `detectorCounts` (never recomputed).

## What's been implemented (2026-06 / current build)
- Parts 0–4 complete and validated end-to-end with a synthetic AMC-style fixture
  (`backend/tests/make_synthetic_plan.py`). Verified: Type 1/2/3 detection, ODPS +
  linked EARLIER APPROVED CASE, occupancy mapping, confidence-tagged review UI,
  Plan Reference panel, source-labelled quantities, placement overlay (points + riser
  + ring), calibration 1:100→28.35 pt/m, dual-source/N.T.S./no-scale fallbacks,
  spacing sanity-check, DWG graceful degradation, startup service-status log.
- No regression: Manual Entry clears the plan session; plan-only report sections are
  absent on manual/legacy sessions (verified).

## Known / out of scope
- PRE-EXISTING bug (NOT this build): `/api/analyze-manual` raises inside the unmodified
  engine (standards_engine when nbc_compliance is None) and the legacy `/confirm` page
  that uses it is therefore broken. Not fixed — engine is out of scope. New upload flow
  uses `/api/analyze-mixed` (works).
- 13 pre-existing failures in `tests/test_rule_engine.py` (assert older IS-2190 counts);
  unrelated to this build.
- Real sample files (KASTURBA_GANDHI, SOT_ALL_FLOOR, Al Makka, digigov_plan, Hotel
  Silver Plate) were NOT uploaded — validated against a synthetic fixture instead.

## Backlog / next
- P1: Auto-zoom/pan the viewer to the detected floor-plan block on load.
- P1: Test against the 5 real files when provided (esp. Al Makka column-vs-dim, digigov
  multi-block scales, Hotel Silver Plate N.T.S. fallback).
- P2: DWG→DXF support if an ODA/LibreDWG converter is added.
- P2: Separate lightweight image endpoint to keep review JSON small.
