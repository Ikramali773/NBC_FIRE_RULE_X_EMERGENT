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

## Iteration 2/3 (real files + follow-ups) — done
Real sample files (5) tested through the pipeline:
- digigov_plan: Type 1/2/3 ALL found; Plan Reference CLEAN (odps_inward_no
  ODPS/2025/120600, scale 1:200; column-bleed garbage rejected by ref-validation);
  multi-block per-scale (Ground/First Floor Plan @ 1:200); placement available with a
  tight block bbox (~10-17% of sheet), sprinkler markers capped at 250 + honest note.
- Al Makka: unit correctly inferred as FEET + N.T.S.; column cross-section labels
  (e.g. C5 12"X27") excluded from dims; floor block geometry detected.
- Kasturba / SOT / Hotel Silver Plate: N.T.S. handled with honest low/medium
  calibration; extractionPath vector_text.
Follow-up tasks completed:
- Performance: extract now two-pass (text-only all pages, geometry only on the floor
  page); find_tables() dropped (too slow on dense CAD); geometry cap 40k segs. Placement
  reuses cached blocks+image → dropped from ~43s to ~0.03s.
- Confirm Flow Repair: legacy `/confirm` now posts to `/api/analyze-mixed` with a
  derived occupancy (was hitting the broken `/api/analyze-manual`). Verified working.
- DWG→DXF optional converter hook (`_try_dwg_to_dxf`, auto-detects `dwg2dxf`/
  `PLAN_DWG2DXF_CMD`); honest fallback when no converter present (current env).
- Fit-To-Block: viewer auto-zooms to the analysed floor-plan block with pan clamped to
  image bounds; BLK / fit-sheet / zoom controls.
- Fixed a self-introduced regression (percentile bbox collapsed on sparse blocks) —
  percentile trim now applies only with >=20 segments, else full endpoint bbox.
Verified by testing agent iteration_2/iteration_3 (backend 100%, frontend flows pass).

## Known / out of scope
- PRE-EXISTING bug (NOT this build): `/api/analyze-manual` raises inside the unmodified
  engine (standards_engine when nbc_compliance is None). The legacy `/confirm` page no
  longer uses it (now posts to `/api/analyze-mixed`); the endpoint itself is left as-is
  since the engine is out of scope.
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
