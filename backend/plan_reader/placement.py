# backend/plan_reader/placement.py
# PART 4 — Suggested Equipment Placement on the actual plan.
#
# The placement algorithm runs entirely in REAL-WORLD METRES using the
# block-specific calibrated scale, then converts every suggested point/line
# BACK into the rendered image's pixel coordinate space so the frontend can
# overlay them with the exact same transform as the plan viewer.
#
# It only ever operates INSIDE the bounding box of the specific floor-plan
# block being analysed. Spacing/coverage come from the EXISTING engine's
# results (we call into them — we do NOT recompute them).

from __future__ import annotations

from .scale_detector import Block

# Real-world reference confirmed from an actual professional fire drawing
REF_SPRINKLER_GRID_M = 3.0
REF_WALL_OFFSET_M = 1.5


def _quadrant(x, y, bbox_px) -> str:
    x0, y0, x1, y1 = bbox_px
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    vert = "north" if y < cy else "south"
    horiz = "west" if x < cx else "east"
    return f"{vert}-{horiz} area"


def compute_placement(
    block: Block,
    zoom: float,
    image_w: int,
    image_h: int,
    analysis: dict,
    extraction: dict,
    floor_label: str,
    riser_px: tuple[float, float] | None = None,
) -> dict:
    """Return a placement overlay in image-pixel coordinates, or an honest
    'not available' payload when scale cannot be established."""

    # ── Honest fallback (point 7): no usable scale for this block ──
    if not block.calibrated_pt_per_m or block.calibrated_pt_per_m <= 0:
        return {
            "available": False,
            "reason": (
                f"Scale for '{block.title}' could not be established "
                f"({block.calibration_source}). Precise point/line placement is "
                f"disabled for this block. The Suggested Equipment Quantities "
                f"(count-based NBC rules) are still shown, as they do not need "
                f"spatial coordinates."
            ),
            "calibration": _calib_dict(block),
        }

    px_per_m = block.calibrated_pt_per_m * zoom
    x0, y0, x1, y1 = [c * zoom for c in block.bbox]
    bbox_px = (x0, y0, x1, y1)
    inset = REF_WALL_OFFSET_M * px_per_m
    ix0, iy0 = x0 + inset, y0 + inset
    ix1, iy1 = x1 - inset, y1 - inset
    if ix1 <= ix0 or iy1 <= iy0:
        return {
            "available": False,
            "reason": f"Floor-plan block '{block.title}' is too small at the detected scale for a meaningful placement grid.",
            "calibration": _calib_dict(block),
        }

    # spacing from the ENGINE (do not recompute)
    detectors = ((analysis or {}).get("nbcCompliance") or {}).get("detectorCounts") or {}
    spacing_m = float(detectors.get("sprinklerSpacingM") or REF_SPRINKLER_GRID_M)
    step = spacing_m * px_per_m

    items = {i.get("id"): i for i in (analysis.get("complianceItems") or [])}

    def required(k):
        it = items.get(k)
        return bool(it and it.get("status") == "required")

    points: list[dict] = []
    side: list[dict] = []

    # ── Sprinkler grid (if sprinkler system required) ──
    sprinkler_positions = []
    if required("sprinkler_system") or detectors.get("totalSprinklers"):
        yy = iy0
        while yy <= iy1 + 1:
            xx = ix0
            while xx <= ix1 + 1:
                sprinkler_positions.append((xx, yy))
                xx += step
            yy += step
        for (px, py) in sprinkler_positions:
            points.append({"type": "sprinkler", "x": round(px, 1), "y": round(py, 1),
                           "floor": floor_label, "clause": "NBC Part 4 Table 7 / IS 15105"})

    # ── Fire extinguishers — travel-distance coverage (~15 m) ──
    ext_step = 15.0 * px_per_m  # IS 2190 max travel distance to extinguisher
    ex_positions = _perimeter_grid(ix0, iy0, ix1, iy1, ext_step)
    ext_total_engine = sum(int(r.get("countRequired") or 0) for r in (analysis.get("requiredExtinguishers") or []))
    for idx, (px, py) in enumerate(ex_positions):
        points.append({"type": "extinguisher", "x": round(px, 1), "y": round(py, 1),
                       "floor": floor_label, "clause": "IS 2190:2024 (max 15 m travel)"})
        side.append({"equipment": "Fire Extinguisher", "floor": floor_label,
                     "location": _quadrant(px, py, bbox_px), "clause": "IS 2190:2024 cl. 7"})

    # ── Hose reels (if required) — near corners at coverage ──
    hose_positions = []
    if required("hose_reel"):
        hose_positions = [(ix0, iy0), (ix1, iy1)]
        for (px, py) in hose_positions:
            points.append({"type": "hose_reel", "x": round(px, 1), "y": round(py, 1),
                           "floor": floor_label, "clause": "IS 884 / IS 3844 (30 m coverage)"})
            side.append({"equipment": "First-Aid Hose Reel", "floor": floor_label,
                         "location": _quadrant(px, py, bbox_px), "clause": "IS 884 / IS 3844"})

    # ── Water source / riser point ──
    riser = riser_px if riser_px else (x0 + inset * 0.5, (y0 + y1) / 2)
    riser = (round(riser[0], 1), round(riser[1], 1))
    points.append({"type": "riser", "x": riser[0], "y": riser[1], "floor": floor_label,
                   "clause": "Riser / water source"})

    # ── Schematic pipe routing: single main riser + a ring per floor ──
    pipes: list[dict] = []
    # main vertical riser line (schematic)
    pipes.append({"kind": "riser", "x1": riser[0], "y1": y0, "x2": riser[0], "y2": y1})
    # horizontal ring/branch loop inset from walls
    ring = [(ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1), (ix0, iy0)]
    for a, b in zip(ring[:-1], ring[1:]):
        pipes.append({"kind": "ring", "x1": round(a[0], 1), "y1": round(a[1], 1),
                      "x2": round(b[0], 1), "y2": round(b[1], 1)})
    # branch from riser to nearest ring corner
    pipes.append({"kind": "ring", "x1": riser[0], "y1": riser[1], "x2": round(ix0, 1), "y2": round(riser[1], 1)})

    # add sprinkler side-table rows (grouped, to keep it readable)
    engine_total = int(detectors.get("totalSprinklers") or 0)
    overlay_note = None
    if sprinkler_positions:
        note = f"{spacing_m:g} m grid, {REF_WALL_OFFSET_M:g} m wall offset, across block"
        side.insert(0, {"equipment": f"Sprinkler grid ({len(sprinkler_positions)} heads shown)",
                        "floor": floor_label,
                        "location": note,
                        "clause": "NBC Part 4 Table 7 / IS 15105"})
        if engine_total and engine_total != len(sprinkler_positions):
            overlay_note = (
                f"The overlay shows {len(sprinkler_positions)} sprinkler heads within the detected "
                f"'{block.title}' block only. The engine's building-wide total is {engine_total} heads "
                f"(all floors / full built-up area) — see the Suggested Equipment Quantities table."
            )

    # ── Sanity check vs real-world reference pattern (point 5) ──
    sanity = _sanity_check(spacing_m)

    return {
        "available": True,
        "block": {"id": block.id, "title": block.title, "bboxPx": [round(c, 1) for c in bbox_px]},
        "calibration": _calib_dict(block),
        "pxPerM": round(px_per_m, 3),
        "spacingM": spacing_m,
        "wallOffsetM": REF_WALL_OFFSET_M,
        "imageWidth": image_w,
        "imageHeight": image_h,
        "riser": {"x": riser[0], "y": riser[1]},
        "points": points,
        "pipes": pipes,
        "sideTable": side,
        "overlayNote": overlay_note,
        "legend": [
            {"symbol": "circle-red", "label": "Fire Extinguisher"},
            {"symbol": "square-blue", "label": "First-Aid Hose Reel"},
            {"symbol": "dot-green", "label": "Sprinkler Head"},
            {"symbol": "diamond-amber", "label": "Riser / Water Source"},
            {"symbol": "line-solid-blue", "label": "Main Riser Pipe (schematic)"},
            {"symbol": "line-dashed-teal", "label": "Ring / Branch Pipe (schematic)"},
        ],
        "sanity": sanity,
        "disclaimerPlacement": "Every suggested position is an ESTIMATE requiring confirmation by a licensed fire protection engineer against the actual building layout.",
        "disclaimerRouting": "Schematic pipe routing — for planning reference only; final hydraulic design must be confirmed by a licensed fire protection engineer.",
    }


def _perimeter_grid(x0, y0, x1, y1, step) -> list[tuple[float, float]]:
    pts = []
    x = x0
    while x <= x1 + 1:
        pts.append((x, y0)); pts.append((x, y1))
        x += step
    y = y0 + step
    while y < y1:
        pts.append((x0, y)); pts.append((x1, y))
        y += step
    # de-dup close points
    out = []
    for p in pts:
        if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 > (step * 0.4) ** 2 for q in out):
            out.append(p)
    return out


def _sanity_check(spacing_m: float) -> dict:
    lo, hi = REF_SPRINKLER_GRID_M * 0.5, REF_SPRINKLER_GRID_M * 1.8
    ok = lo <= spacing_m <= hi
    return {
        "ok": ok,
        "reference": f"~{REF_SPRINKLER_GRID_M:g} m x {REF_SPRINKLER_GRID_M:g} m grid, {REF_WALL_OFFSET_M:g} m max wall offset",
        "note": ("Placement grid is consistent with the real-world reference pattern."
                 if ok else
                 f"WARNING: computed spacing {spacing_m:g} m deviates from the typical "
                 f"~{REF_SPRINKLER_GRID_M:g} m reference grid — verify the engine spacing and scale."),
    }


def _calib_dict(block: Block) -> dict:
    return {
        "title": block.title,
        "scaleNote": block.scale_note,
        "unit": block.unit,
        "unitSource": block.unit_source,
        "nts": block.nts,
        "confidence": block.calibration_confidence,
        "source": block.calibration_source,
        "conflict": block.conflict,
        "ptPerM": block.calibrated_pt_per_m,
    }
