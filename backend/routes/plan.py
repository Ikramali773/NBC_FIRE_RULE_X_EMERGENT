# backend/routes/plan.py
# NEW LAYER endpoints — building-plan reading + equipment placement.
#
#   POST /api/plan/extract    multipart upload → review payload (fields with
#                             confidence, table types, Plan Reference metadata,
#                             geometry availability, per-block scale, page image)
#   POST /api/plan/placement  confirmed inputs + engine analysis → placement
#                             overlay (points/lines in image-pixel coords) OR an
#                             honest 'not available, here's why'
#   GET  /api/plan/status     configured-service status (Part 2)
#
# These routes NEVER touch the calculation engine internals — they only
# READ an AnalysisResult that the existing engine already produced.

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from plan_reader.config import get_plan_config
from plan_reader.pdf_extractor import PlanDocument
from plan_reader import table_parser
from plan_reader import field_mapper
from plan_reader.scale_detector import find_blocks
from plan_reader.placement import compute_placement
from plan_reader.equipment_estimator import estimate_quantities
from plan_reader.ocr import ocr_page_png, ocr_and_extract_plan, synthesize_multipage_plan
from plan_reader import store

router = APIRouter()

MAX_FILE_SIZE = 12 * 1024 * 1024  # 12MB


@router.get("/api/plan/status")
async def plan_status():
    cfg = get_plan_config()
    return {
        "coreExtraction": "enabled",
        "tableDetection": "enabled",
        "aiOcr": "enabled" if cfg["ai_ocr_active"] else "disabled",
        "aiOcrRequested": cfg["ai_ocr_requested"],
        "aiOcrKeyPresent": cfg["ai_ocr_key_present"],
        "renderZoom": cfg["render_zoom"],
        "note": "System is fully functional with zero external services configured.",
    }


def _choose_floor_page_by_text(pages: list) -> int:
    """Pick the floor-plan page from TEXT only (fast — no geometry needed).

    Scores each page by how many strong floor-plan titles it contains and
    picks the best; 'KEY PLAN' alone does not qualify a page.
    """
    strong = ["GROUND FLOOR PLAN", "TYPICAL FLOOR PLAN", "FIRST FLOOR PLAN",
              "SECOND FLOOR PLAN", "BASEMENT PLAN", "TERRACE PLAN", "FLOOR PLAN"]
    best_idx, best_score = None, 0
    for p in pages:
        up = p.text.upper()
        score = sum(up.count(k) for k in strong)
        if score > best_score:
            best_score, best_idx = score, p.index
    if best_idx is not None:
        return best_idx
    # fallback: any page mentioning a floor, else page 0
    for p in pages:
        if "FLOOR" in p.text.upper() and "KEY PLAN" not in p.text.upper():
            return p.index
    return pages[0].index if pages else 0


@router.post("/api/plan/extract")
async def plan_extract(file: UploadFile = File(...)):
    try:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            return JSONResponse({"error": f"File too large ({len(content)/1024/1024:.1f}MB). Max 12MB."}, status_code=400)

        doc = PlanDocument(content, file.filename or "plan")
        cfg = get_plan_config()

        # ── DWG / open failure → honest degraded response ──
        if doc.error or doc.doc is None:
            return JSONResponse({
                "planId": None,
                "fileName": file.filename,
                "originalFormat": doc.original_format,
                "extractionPath": "dwg_unsupported" if doc.original_format == "dwg" else "open_failed",
                "tablesFound": {"type1": False, "type2": False, "type3": False},
                "fields": [], "prefill": {}, "planReference": None, "areaStatement": None,
                "geometryAvailable": False, "blocks": [], "pageImage": None,
                "warnings": [doc.error or "Could not open file."],
                "aiOcr": "enabled" if cfg["ai_ocr_active"] else "disabled",
            })

        # ── read all pages (TEXT ONLY — fast; geometry/tables deferred) ──
        pages = [doc.read_page(i, with_geometry=False, with_tables=False)
                 for i in range(doc.page_count)]
        full_text = "\n".join(p.text for p in pages)
        all_tables: list = []  # find_tables() is too slow on dense CAD sheets;
        # the text layer + regex parser covers Table Types 1/2/3.

        # ── scanned / multi-page fallback (optional AI OCR) ──
        extraction_path = "vector_text"
        scanned_pages = [p for p in pages if p.is_scanned]
        ai_extracted_data = None
        if len(full_text.strip()) < 60 and not cfg["ai_ocr_active"]:
            extraction_path = "scanned_no_ocr"
        elif (len(full_text.strip()) < 60 or len(pages) > 1 or scanned_pages) and cfg["ai_ocr_active"]:
            pages_to_ocr = pages[:10]  # Process all drawing sheets up to 10

            async def _proc_page(sp):
                img = doc.render_png(sp.index, zoom=cfg["render_zoom"])
                return await ocr_and_extract_plan(img["base64"])

            page_results = await asyncio.gather(*[_proc_page(sp) for sp in pages_to_ocr], return_exceptions=True)
            valid_results = [r for r in page_results if isinstance(r, dict)]
            if valid_results:
                ai_extracted_data = synthesize_multipage_plan(valid_results)
                full_text = full_text + "\n" + ai_extracted_data.get("ocr_text", "")
                extraction_path = "scanned_ocr"

        # ── table detection (Type 1 / 2 / 3) from the text layer ──
        type1 = table_parser.parse_type1_fsi(full_text, all_tables)
        type2 = table_parser.parse_type2_occupancy(full_text, all_tables)
        type3 = table_parser.parse_type3_metadata(full_text, all_tables)

        if ai_extracted_data and ai_extracted_data.get("tablesFound"):
            tf = ai_extracted_data["tablesFound"]
            if tf.get("type1") and not type1:
                type1 = {"values": {"total_built_up_area": ai_extracted_data.get("prefill", {}).get("totalBuiltUpArea"), "plot_area": ai_extracted_data.get("prefill", {}).get("plotArea")}, "confidence": "high", "raw_signals": ["AI OCR Table Type 1"]}
            if tf.get("type2") and not type2:
                type2 = {"values": {"inferred_occupancy_group": (ai_extracted_data.get("prefill", {}).get("primaryOccupancy") or "F")[:1]}, "confidence": "high"}

        # ── map to form fields ──
        mapping = field_mapper.build_mapping(full_text, type1, type2, ai_data=ai_extracted_data)

        # ── per-block scale on the chosen floor page (geometry pass here only) ──
        floor_idx = _choose_floor_page_by_text(pages)
        floor_page = doc.read_page(floor_idx, with_geometry=True, with_tables=False)
        blocks = find_blocks(floor_page)
        geometry_available = any(b.is_floor_plan and b.has_geometry for b in blocks)

        img = doc.render_png(floor_idx, zoom=cfg["render_zoom"])
        original_format = doc.original_format
        converted_from = doc.converted_from

        plan_id = store.put({
            "bytes": content,
            "filename": file.filename or "plan",
            "floor_page_index": floor_idx,
            "zoom": cfg["render_zoom"],
            "blocks": [b.to_dict() for b in blocks],
            "image": img,
        })

        blocks_out = [{
            "id": b.id, "title": b.title, "isFloorPlan": b.is_floor_plan,
            "hasGeometry": b.has_geometry, "scaleNote": b.scale_note,
            "unit": b.unit, "unitSource": b.unit_source, "nts": b.nts,
            "calibrationConfidence": b.calibration_confidence,
            "calibrationSource": b.calibration_source, "conflict": b.conflict,
            "bbox": [round(c, 1) for c in b.bbox],
        } for b in blocks]

        doc.close()

        return JSONResponse({
            "planId": plan_id,
            "fileName": file.filename,
            "originalFormat": original_format,
            "convertedFrom": converted_from,
            "pageCount": len(pages),
            "extractionPath": extraction_path,
            "tablesFound": {"type1": bool(type1), "type2": bool(type2), "type3": bool(type3)},
            "fields": mapping["fields"],
            "prefill": mapping["prefill"],
            "planReference": (type3 or {}).get("values") if type3 else None,
            "planReferenceConfidence": (type3 or {}).get("confidence") if type3 else None,
            "areaStatement": (type2 or {}).get("values") if (type2 and type2.get("structured")) else None,
            "geometryAvailable": geometry_available,
            "floorPageIndex": floor_idx,
            "blocks": blocks_out,
            "pageImage": img,
            "warnings": mapping["warnings"],
            "aiOcr": "enabled" if cfg["ai_ocr_active"] else "disabled",
            "analyzedAt": datetime.now(timezone.utc).isoformat(),
        })

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": f"Plan extraction failed: {exc}"}, status_code=500)


class PlacementRequest(BaseModel):
    planId: str | None = None
    blockId: str | None = None
    floorLabel: str = "Ground Floor"
    riser: dict | None = None
    buildingInput: dict = {}
    analysis: dict = {}


@router.post("/api/plan/placement")
async def plan_placement(body: PlacementRequest):
    try:
        # equipment quantities are ALWAYS available (count-based, no geometry)
        quantities = estimate_quantities(body.analysis, body.buildingInput)

        if not body.planId:
            return JSONResponse({
                "available": False,
                "reason": "Equipment placement requires an uploaded plan file. This analysis did not originate from an uploaded plan (e.g. Manual Entry).",
                "quantities": quantities,
            })

        entry = store.get(body.planId)
        if not entry:
            return JSONResponse({
                "available": False,
                "reason": "The uploaded plan is no longer available (session expired). Please re-upload to generate placement.",
                "quantities": quantities,
            })

        # Reuse the blocks + rendered image computed during extraction — no
        # need to re-open the PDF or re-run the slow geometry pass.
        from plan_reader.scale_detector import Block
        zoom = entry["zoom"]
        img = entry.get("image")
        blocks = [Block.from_dict(d) for d in (entry.get("blocks") or [])]

        if not blocks or img is None:
            return JSONResponse({
                "available": False,
                "reason": "No cached plan geometry is available for placement. Please re-upload the plan.",
                "quantities": quantities,
            })

        block = None
        if body.blockId:
            block = next((b for b in blocks if b.id == body.blockId), None)
        if block is None:
            block = next((b for b in blocks if b.is_floor_plan and b.has_geometry), None)
        if block is None:
            block = next((b for b in blocks if b.is_floor_plan), None) or blocks[0]

        if block is None or not block.has_geometry:
            return JSONResponse({
                "available": False,
                "reason": "No floor-plan block with usable vector line geometry was found — placement needs real wall geometry. Equipment quantities are still available below.",
                "quantities": quantities,
            })

        riser_px = None
        if body.riser and "x" in body.riser and "y" in body.riser:
            riser_px = (float(body.riser["x"]), float(body.riser["y"]))

        result = compute_placement(
            block=block, zoom=zoom,
            image_w=img["width"], image_h=img["height"],
            analysis=body.analysis, extraction=body.buildingInput,
            floor_label=body.floorLabel, riser_px=riser_px,
        )
        result["quantities"] = quantities
        result["pageImage"] = img
        result["blocks"] = [{"id": b.id, "title": b.title, "isFloorPlan": b.is_floor_plan,
                             "hasGeometry": b.has_geometry} for b in blocks]
        return JSONResponse(result)

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": f"Placement failed: {exc}"}, status_code=500)
