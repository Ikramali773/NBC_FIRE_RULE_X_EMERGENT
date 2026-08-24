# backend/plan_reader/equipment_estimator.py
# PART 3 §1 — Suggested Equipment Quantities.
#
# Consumes the EXISTING engine's AnalysisResult (read-only). Every line
# carries an explicit source label:
#   - "Per NBC Part 4 calculation"  → value comes straight from the code's
#      own rules (extinguisher counts, sprinkler counts from the engine).
#   - "Estimated per <IS standard> — confirm with a licensed fire
#      protection engineer" → industry-standard assumption not explicit in
#      NBC Part 4 itself.
# One disclaimer is shown once at the top of the section (frontend), not
# per line.

from __future__ import annotations


def estimate_quantities(analysis: dict, extraction: dict) -> list[dict]:
    lines: list[dict] = []
    nbc = (analysis or {}).get("nbcCompliance") or {}
    detectors = nbc.get("detectorCounts") or {}
    items = {i.get("id"): i for i in (analysis.get("complianceItems") or [])}
    floors = int(extraction.get("numberOfFloors") or len(extraction.get("floorAreas") or [1]) or 1)
    total_area = float(extraction.get("totalFloorArea") or sum(extraction.get("floorAreas") or [0]) or 0)
    plot_area = float(extraction.get("plotArea") or 0)

    def required(item_id: str) -> bool:
        it = items.get(item_id)
        return bool(it and it.get("status") == "required")

    # ── Fire extinguishers (from engine — IS 2190 via rule engine) ──
    ext_total = sum(int(r.get("countRequired") or 0) for r in (analysis.get("requiredExtinguishers") or []))
    if ext_total > 0:
        classes = ", ".join(sorted({r.get("fireClass", "?") for r in analysis.get("requiredExtinguishers", [])}))
        lines.append({
            "equipment": "Portable Fire Extinguishers",
            "quantity": ext_total,
            "unit": "units",
            "formula": f"Rule-engine total across floors (classes {classes}); IS 2190:2024 coverage.",
            "source": "Per NBC Part 4 calculation",
            "sourceType": "nbc",
        })

    # ── Sprinkler heads (from engine detector counts when computed) ──
    total_sprinklers = detectors.get("totalSprinklers")
    if total_sprinklers:
        cov = detectors.get("sprinklerCoverageM2")
        spc = detectors.get("sprinklerSpacingM")
        lines.append({
            "equipment": "Sprinkler Heads",
            "quantity": int(total_sprinklers),
            "unit": "heads",
            "formula": f"floor area ÷ coverage ({cov} m²/head @ {spc} m spacing) — engine computed.",
            "source": "Per NBC Part 4 calculation",
            "sourceType": "nbc",
        })
    elif required("sprinkler_system"):
        est = max(1, round(total_area / 12.0)) if total_area else None
        lines.append({
            "equipment": "Sprinkler Heads",
            "quantity": est,
            "unit": "heads",
            "formula": "≈ built-up area ÷ 12 m² per head (light/ordinary hazard).",
            "source": "Estimated per IS 15105 — confirm with a licensed fire protection engineer",
            "sourceType": "estimate",
        })

    # ── First-aid hose reels ──
    if required("hose_reel"):
        qty = floors  # one per floor landing is the common practice
        lines.append({
            "equipment": "First-Aid Hose Reels",
            "quantity": qty,
            "unit": "units",
            "formula": "≈ 1 per floor landing (36 m hose, 30 m coverage).",
            "source": "Estimated per IS 884 / IS 3844 — confirm with a licensed fire protection engineer",
            "sourceType": "estimate",
        })

    # ── Landing valves (wet riser / down comer) ──
    if required("wet_riser") or required("down_comer"):
        qty = floors
        lines.append({
            "equipment": "Landing Valves",
            "quantity": qty,
            "unit": "units",
            "formula": "≈ 1 landing valve per floor per riser.",
            "source": "Estimated per IS 3844 — confirm with a licensed fire protection engineer",
            "sourceType": "estimate",
        })

    # ── Yard hydrants ──
    if required("yard_hydrant"):
        # ~1 hydrant per 45 m of plot perimeter; approximate perimeter from
        # plot area assuming a square plot when perimeter isn't known.
        if plot_area > 0:
            side = plot_area ** 0.5
            perimeter = 4 * side
            qty = max(2, round(perimeter / 45.0))
            basis = f"plot perimeter ≈ {perimeter:.0f} m ÷ 45 m spacing"
        else:
            qty = 2
            basis = "minimum practical count (plot dimensions unknown)"
        lines.append({
            "equipment": "External Yard Hydrants",
            "quantity": qty,
            "unit": "units",
            "formula": f"≈ 1 per 45 m spacing ({basis}).",
            "source": "Estimated per IS 3844 / NBC Part 4 — confirm with a licensed fire protection engineer",
            "sourceType": "estimate",
        })

    return lines
