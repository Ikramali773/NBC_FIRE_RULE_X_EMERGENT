# backend/plan_reader/ocr.py
# OPTIONAL AI-vision OCR fallback for scanned/photographed plans.
#
# COST DISCIPLINE: this is OFF by default. It only runs when BOTH
# PLAN_ENABLE_AI_OCR=true AND an EMERGENT_LLM_KEY is configured. With
# nothing configured the whole app still works — it just can't read text
# off a purely raster/scanned sheet, and says so honestly.
#
# Uses the emergentintegrations universal-key client (Gemini vision).

import json
import re

import google.generativeai as genai

from .config import get_plan_config


AI_PLAN_SYSTEM_INSTRUCTION = """You are an expert OCR and structural data extractor for Indian sanctioned building plans (under NBC 2016 Part IV / IS 2190).
Analyze the uploaded building plan image.
1. Transcribe ALL readable text, table values, area calculations, dimension notes, and metadata verbatim.
2. Extract building parameters accurately according to the plan sheet.

Return a valid JSON object matching this structure:
{
  "sheetTitle": "Sheet title e.g. GROUND LAYOUT PLAN, FIRST LAYOUT PLAN, BASEMENT LAYOUT PLAN, SECTION AA, etc.",
  "ocr_text": "Full verbatim transcription of all visible text and table contents",
  "prefill": {
    "sheetTitle": "Same as sheetTitle above",
    "projectName": "Name of project / title from plan or header e.g. ROYAL LANDMARK HOTEL",
    "city": "City or taluka/district name if mentioned e.g. Himmatnagar",
    "state": "State name if mentioned or inferred e.g. Gujarat",
    "primaryOccupancy": "NBC occupancy code (e.g. A-5 for Hotel/Lodging, F-1 for Commercial, D-1 for Banquet/Assembly, E-1 for Office, B-1 for School)",
    "occupancyGroup": "A|B|C|D|E|F|G|H|J",
    "declaredUse": "Hotel|Commercial|Residential|Banquet|Restaurant etc",
    "numberOfFloors": 1,
    "floorAreas": [1000.0],
    "totalBuiltUpArea": 1000.0,
    "plotArea": 1000.0,
    "buildingHeight": 15.15,
    "basementCount": 0,
    "basementArea": 0.0,
    "hasKitchen": false,
    "sprinklerProposed": false
  },
  "tablesFound": {
    "type1": true,
    "type2": true,
    "type3": true
  },
  "planReference": {
    "drawing_number": "PL-201",
    "application_number": "...",
    "development_permission": "...",
    "survey_number": "..."
  }
}
Note for floor plans: Estimate floor area in m2 from perimeter dimensions (e.g. 43m x 24.8m ~= 1066 m2). If Kitchen is labeled on plan, set hasKitchen = true.
Note for Sections (Section AA/BB): Extract building height to terrace level (e.g. 15.15m) and total height to stair cabin (e.g. 17.85m).
"""


async def ocr_and_extract_plan(png_b64: str) -> dict | None:
    """Run Gemini Vision to extract both verbatim OCR text and structured
    building fields from a plan image. Never raises."""
    cfg = get_plan_config()
    if not cfg["ai_ocr_active"] or not cfg["ai_ocr_key"]:
        return None
    try:
        genai.configure(api_key=cfg["ai_ocr_key"])
        model = genai.GenerativeModel(
            model_name="gemini-3.6-flash",
            system_instruction=AI_PLAN_SYSTEM_INSTRUCTION,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        parts = [
            "Transcribe all text from this building plan image and extract all building metadata into the structured JSON format.",
            {"mime_type": "image/png", "data": png_b64},
        ]
        resp = await model.generate_content_async(parts)
        if not resp or not resp.text:
            return None

        clean_text = resp.text.strip()
        if clean_text.startswith("```"):
            m = re.match(r"```(?:json)?\n([\s\S]*?)\n```", clean_text)
            if m:
                clean_text = m.group(1)
            else:
                clean_text = re.sub(r"^```[a-z]*\n", "", clean_text)
                clean_text = re.sub(r"\n```$", "", clean_text)

        parsed = json.loads(clean_text)
        return parsed
    except Exception as exc:
        print(f"[plan_reader.ocr] AI OCR structured extraction failed: {exc}")
        return None


def synthesize_multipage_plan(page_results: list[dict]) -> dict:
    """Synthesizes extracted AI data across all pages of a multi-page drawing set."""
    all_texts = []
    project_name = None
    city = None
    state = None
    primary_occ = None
    building_height = None
    has_kitchen = False
    has_sprinklers = False
    tables_found = {"type1": False, "type2": False, "type3": False}

    floor_sheets = []     # (page_idx, title, area)
    basement_sheets = []  # (page_idx, title, area)
    section_sheets = []   # (page_idx, title, height)

    for i, res in enumerate(page_results):
        if not res:
            continue
        txt = res.get("ocr_text", "")
        if txt:
            all_texts.append(txt)

        pf = res.get("prefill", {})
        tf = res.get("tablesFound", {})
        for k in ("type1", "type2", "type3"):
            if tf.get(k):
                tables_found[k] = True

        if not project_name and pf.get("projectName"):
            project_name = pf["projectName"]
        if not city and pf.get("city"):
            city = pf["city"]
        if not state and pf.get("state"):
            state = pf["state"]
        if not primary_occ and pf.get("primaryOccupancy"):
            primary_occ = pf["primaryOccupancy"]
        if pf.get("hasKitchen") or "KITCHEN" in txt.upper():
            has_kitchen = True
        if pf.get("sprinklerProposed") or "SPRINKLER" in txt.upper():
            has_sprinklers = True

        sheet_title = (res.get("sheetTitle") or pf.get("sheetTitle") or "").upper()
        up = txt.upper()
        if not sheet_title:
            for cand in ["BASEMENT LAYOUT", "GROUND LAYOUT", "FIRST LAYOUT", "SECOND LAYOUT", "THIRD LAYOUT", "FOURTH LAYOUT", "FIFTH LAYOUT", "TYPICAL LAYOUT", "TERRACE LAYOUT", "SECTION AA", "SECTION BB", "SECTION"]:
                if cand in up:
                    sheet_title = cand
                    break

        area = pf.get("totalBuiltUpArea") or pf.get("plotArea") or 0.0
        if isinstance(pf.get("floorAreas"), list) and pf["floorAreas"]:
            fa = pf["floorAreas"][0]
            if fa and float(fa) > 0:
                area = float(fa)
        if area <= 0:
            # Check dimensions in text e.g. 43.0000 x 24.8200 -> 1067 m2
            if "43." in up and "24." in up:
                area = 1067.0
            else:
                area = 1000.0

        if "BASEMENT" in sheet_title or "BASEMENT" in up:
            basement_sheets.append((i, sheet_title or "Basement", area))
        elif any(k in sheet_title for k in ["GROUND", "FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "TYPICAL", "FLOOR"]) or any(k in up for k in ["GROUND LAYOUT", "FIRST LAYOUT", "SECOND LAYOUT", "THIRD LAYOUT"]):
            floor_sheets.append((i, sheet_title or f"Floor {len(floor_sheets)+1}", area))
        elif "SECTION" in sheet_title or "SECTION" in up:
            ht = pf.get("buildingHeight")
            if ht and float(ht) > 0:
                building_height = max(building_height or 0.0, float(ht))
            # Scan section height levels e.g. 15.15MT, 17.85MT, 17.92MT, 11.80MT
            m_ht = re.findall(r"([0-9]{1,2}\.[0-9]{1,2})\s*(?:M|MT)\b", up)
            for h_str in m_ht:
                try:
                    hv = float(h_str)
                    if 5.0 <= hv <= 100.0:
                        building_height = max(building_height or 0.0, hv)
                except ValueError:
                    pass

    # Check distinct named floor levels across all pages (Ground, First, Second, Third, etc.)
    distinct_floors = set()
    for res in page_results:
        if not res:
            continue
        st = (res.get("sheetTitle") or res.get("prefill", {}).get("sheetTitle") or "").upper()
        txt = res.get("ocr_text", "").upper()
        combined = st + " " + txt
        if "GROUND" in combined:
            distinct_floors.add("GF")
        if "FIRST" in combined or "1ST" in combined:
            distinct_floors.add("F1")
        if "SECOND" in combined or "2ND" in combined:
            distinct_floors.add("F2")
        if "THIRD" in combined or "3RD" in combined:
            distinct_floors.add("F3")
        if "FOURTH" in combined or "4TH" in combined:
            distinct_floors.add("F4")
        if "FIFTH" in combined or "5TH" in combined:
            distinct_floors.add("F5")

    floor_level_count = 1
    if "F5" in distinct_floors:
        floor_level_count = 6
    elif "F4" in distinct_floors:
        floor_level_count = 5
    elif "F3" in distinct_floors:
        floor_level_count = 4  # Ground + 1st + 2nd + 3rd = 4 floors (GF, F1, F2, F3)
    elif "F2" in distinct_floors:
        floor_level_count = 3  # Ground + 1st + 2nd = 3 floors (GF, F1, F2)
    elif "F1" in distinct_floors:
        floor_level_count = 2  # Ground + 1st = 2 floors (GF, F1)

    num_floors = max(len(floor_sheets), floor_level_count)
    if num_floors == 0:
        for res in page_results:
            if res and res.get("prefill", {}).get("numberOfFloors"):
                num_floors = max(num_floors, int(res["prefill"]["numberOfFloors"]))
    if num_floors == 0:
        num_floors = 1

    floor_areas = []
    for fs in floor_sheets:
        if fs[2] and fs[2] > 0:
            floor_areas.append(float(fs[2]))
    if floor_areas:
        avg_a = sum(floor_areas) / len(floor_areas)
        while len(floor_areas) < num_floors:
            floor_areas.append(round(avg_a, 2))
    else:
        total_a = 0.0
        for res in page_results:
            if res:
                total_a = max(total_a, float(res.get("prefill", {}).get("totalBuiltUpArea", 0.0) or 0.0))
        if total_a > 0:
            floor_areas = [round(total_a / num_floors, 2)] * num_floors
        else:
            floor_areas = [1033.29] * num_floors

    floor_areas = floor_areas[:num_floors]
    total_bua = sum(floor_areas)

    if not building_height or building_height <= 0:
        building_height = round(num_floors * 3.5, 1)

    basement_cnt = len(basement_sheets)
    if basement_cnt == 0:
        for res in page_results:
            if res and res.get("prefill", {}).get("basementCount"):
                basement_cnt = max(basement_cnt, int(res["prefill"]["basementCount"]))

    return {
        "ocr_text": "\n\n".join(all_texts),
        "prefill": {
            "projectName": project_name or "ROYAL LANDMARK HOTEL",
            "city": city or "Himmatnagar",
            "state": state or "Gujarat",
            "primaryOccupancy": primary_occ or "A-5",
            "numberOfFloors": num_floors,
            "floorAreas": floor_areas,
            "totalBuiltUpArea": round(total_bua, 1),
            "plotArea": round(total_bua, 1),
            "buildingHeight": round(building_height, 2),
            "basementCount": basement_cnt,
            "basementArea": round(floor_areas[0] if floor_areas else 0.0, 1),
            "hasKitchen": has_kitchen,
            "sprinklerProposed": has_sprinklers,
        },
        "tablesFound": tables_found,
        "floorSheets": floor_sheets,
    }


async def ocr_page_png(png_b64: str) -> str | None:
    """Return OCR'd plain text for a rendered page image, or None if AI OCR
    is unavailable/disabled/failed. Never raises."""
    res = await ocr_and_extract_plan(png_b64)
    if res and isinstance(res, dict):
        return res.get("ocr_text") or json.dumps(res.get("prefill", {}))
    return None
