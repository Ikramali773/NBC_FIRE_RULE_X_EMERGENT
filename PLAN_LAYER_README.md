# Building-Plan Reading & Equipment-Placement Layer

A NEW layer added around the existing, **unmodified** NBC Part 4 calculation
engine. It reads uploaded building plans, proposes values for the existing
Manual Entry form (with confidence + user review), and enhances the report with
suggested equipment quantities and on-plan placement.

## Architecture (module boundary)
```
backend/plan_reader/            ← NEW, self-contained. Never imports engine internals.
  config.py                     ← env-driven service config + startup status log
  pdf_extractor.py              ← PyMuPDF: text+coords, vector lines, tables, render
  table_parser.py               ← Table Type 1 (FSI) / 2 (occupancy) / 3 (ODPS metadata)
  scale_detector.py             ← per-BLOCK scale, unit inference, column-label exclusion
  field_mapper.py               ← parsed data → BuildingInput fields + confidence + source
  equipment_estimator.py        ← Part 3 §1 quantities (labelled NBC vs estimate)
  placement.py                  ← Part 4 placement + schematic riser+ring routing
  ocr.py                        ← OPTIONAL AI-vision OCR (off by default)
  store.py                      ← in-memory plan store (no DB, no disk)
backend/routes/plan.py          ← POST /api/plan/extract, /api/plan/placement, GET /api/plan/status
frontend/src/app/upload/        ← NEW upload → review → confirm flow
frontend/src/components/PlanViewer.tsx     ← zoom/pan viewer + anchored SVG overlay
frontend/src/components/PlanSections.tsx   ← report additions (plan-only)
```
The engine (`rule_engine.py`, `engines/`, `*_checker.py`) is **read-only** to this
layer — it is consumed only through the existing `AnalysisResult` interface.

## Why this technical approach
- **PyMuPDF (fitz)** is already installed and does everything the core needs at
  **zero cost, zero external calls**: text with coordinates, `get_drawings()` for
  real vector wall geometry, `find_tables()`, and page rendering for the viewer.
  This satisfies the "must fully function with zero services configured" rule.
- **Regex/keyword table parsing** rather than an LLM, so Table Types 1/2/3 are
  detected deterministically and for free. Table Type 3 metadata is captured and
  displayed but never feeds the engine.
- **Optional AI-vision OCR** only fills the one gap PyMuPDF cannot cover — purely
  raster/scanned sheets with no text layer — and is strictly opt-in.
- **DWG** is a binary CAD format needing an external converter (not bundled, not
  zero-cost); the layer detects it and degrades honestly, asking for PDF/DXF.

## Configuration (all OPTIONAL — env vars only, never hardcoded)
Set in `/app/backend/.env`:

| Variable | Default | What it does | Where to get it |
|---|---|---|---|
| `PLAN_ENABLE_AI_OCR` | unset (off) | Allow AI-vision OCR fallback on **scanned** pages only | n/a (flag) |
| `EMERGENT_LLM_KEY` | unset | Universal key powering the optional Gemini OCR (free-tier compatible) | Emergent profile → Universal Key. Or replace with your own Gemini key. |
| `PLAN_RENDER_ZOOM` | `2.0` | Pixmap render zoom for the in-app plan viewer | n/a |

With none set, the app runs fully in **vector-text-only** mode. Each service's
status is printed on backend startup, e.g.:
```
[plan_reader]   Optional AI-vision OCR (Gemini)      : DISABLED (not configured — vector-text-only mode)
```
Check `GET /api/plan/status` to confirm configuration at runtime.

## Endpoints
- `POST /api/plan/extract` (multipart `file`) → review payload: mapped fields with
  confidence + source, `tablesFound`, `planReference` (Type 3), `areaStatement`
  (Type 2), `geometryAvailable`, per-block scale `blocks`, and a rendered
  `pageImage`. **Nothing is auto-applied** — the UI requires explicit confirmation.
- `POST /api/plan/placement` → `{available, points, pipes, sideTable, legend,
  calibration, sanity, quantities, pageImage}` in image-pixel coordinates, or an
  honest `{available:false, reason}` (still returns count-based `quantities`).
- `GET /api/plan/status` → configured-service status.

## Guarantees
- No regression: Manual Entry, the engine, and the existing report are unchanged.
  Manual sessions clear the plan session, so plan-only report sections never appear.
- No silent auto-application: every extracted/estimated value is reviewable and
  requires confirmation before analysis.
- Graceful degradation everywhere (DWG, scanned-no-OCR, no-scale block, expired
  session) → clear "not available, here's why" instead of failing or guessing.
