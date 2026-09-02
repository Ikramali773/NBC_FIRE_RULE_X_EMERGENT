# backend/plan_reader/field_mapper.py
# Maps parsed plan data → the EXISTING Manual Entry form fields
# (BuildingInput camelCase), attaching a confidence + human source label
# to every value. NOTHING here is auto-trusted: the frontend shows all of
# this for review/correction and the user must confirm before it is used.
#
# Authority rule (from spec): Table Type 1 / Type 2 values are the PRIMARY
# source for the fields they cover and override measurement/text-derived
# values. Table Type 3 is reference-only and NEVER mapped to a form field.

from __future__ import annotations

import re

# maps a coarse NBC group letter → a sensible default subdivision code the
# existing engine understands. The user can change it on the review screen.
_GROUP_DEFAULT_SUB = {
    "A": "A-4", "B": "B-1", "C": "C-2", "D": "D-1", "E": "E-1",
    "F": "F-1", "G": "G-1", "H": "H", "J": "J",
}
_GROUP_LABEL = {
    "A": "Residential", "B": "Educational", "C": "Institutional",
    "D": "Assembly", "E": "Business", "F": "Mercantile",
    "G": "Industrial", "H": "Storage", "J": "Hazardous",
}


def _field(group, key, label, value, unit, confidence, source, note=""):
    return {
        "group": group, "key": key, "label": label,
        "value": value, "unit": unit,
        "confidence": confidence, "source": source, "note": note,
    }
def build_mapping(text: str, type1: dict | None, type2: dict | None, ai_data: dict | None = None) -> dict:
    """Return {'fields': [...], 'prefill': {...camelCase...}, 'warnings': [...]}"""
    fields: list[dict] = []
    prefill: dict = {}
    warnings: list[str] = []
    up = text.upper()

    ai_pf = (ai_data or {}).get("prefill", {}) if isinstance(ai_data, dict) else {}

    # ── Project name ──
    proj = ai_pf.get("projectName")
    if not proj:
        m = re.search(r"(?:PROPOSED\s+(?:LAY\s*OUT\s+)?PLAN\s+FOR\s+[A-Za-z0-9 ,.&'\-/]+?)(?=,\s*AT|\n|$)", text, re.IGNORECASE)
        if m:
            proj = m.group(0).strip()
        else:
            m = re.search(r"(?:NAME\s+OF\s+(?:PROJECT|BUILDING|OWNER)|PROJECT)\s*[:\-]\s*([A-Za-z0-9 ,.&'\-]{3,80})", text, re.IGNORECASE)
            if m:
                proj = m.group(1).strip()
    if proj and proj.upper().strip(" .-") not in ("NA", "N.A", "NIL", "NONE", "-"):
        conf = "high" if ai_pf.get("projectName") else "medium"
        src = "AI Vision Extraction" if ai_pf.get("projectName") else "Text on plan"
        fields.append(_field("project", "projectName", "Project Name", proj, "", conf, src))
        prefill["projectName"] = proj

    # ── City / State ──
    city = ai_pf.get("city")
    if not city:
        m_city = re.search(r"(?:AT\s*&\s*TA|TALUKA|DIST|DISTRICT)[\s\-:]*([A-Za-z]+)", text, re.IGNORECASE)
        if m_city:
            city = m_city.group(1).strip().title()
        else:
            for city_kw in ["AHMEDABAD", "MUMBAI", "SURAT", "VADODARA", "RAJKOT", "PUNE", "DELHI", "BENGALURU", "CHENNAI", "HYDERABAD", "MEHSANA", "VADNAGAR", "GANDHINAGAR"]:
                if city_kw in up:
                    city = city_kw.title()
                    break
    if city:
        conf = "high" if ai_pf.get("city") else "medium"
        src = "AI Vision Extraction" if ai_pf.get("city") else "Text on plan"
        fields.append(_field("project", "city", "City", city, "", conf, src))
        prefill["city"] = city

    state = ai_pf.get("state")
    if not state:
        if any(g in up for g in ["GUJARAT", "MEHSANA", "VADNAGAR", "SURAT", "AHMEDABAD"]):
            state = "Gujarat"
        elif any(m in up for m in ["MAHARASHTRA", "MUMBAI", "PUNE"]):
            state = "Maharashtra"
    if state:
        prefill["state"] = state

    # ── Number of floors ──
    floors = ai_pf.get("numberOfFloors")
    if not floors:
        m = re.search(r"\bG\s*\+\s*(\d{1,2})\b", up)
        if m:
            floors = int(m.group(1)) + 1
        else:
            m = re.search(r"GROUND\s*\+\s*(\d{1,2})", up)
            if m:
                floors = int(m.group(1)) + 1
            else:
                m = re.search(r"(\d{1,2})\s*FLOORS?", up)
                if m:
                    floors = int(m.group(1))
    if not floors:
        floors = 1
    floors = int(floors)
    conf = "high" if ai_pf.get("numberOfFloors") else "medium"
    src = "AI Vision Extraction" if ai_pf.get("numberOfFloors") else "Floor notation on plan"
    fields.append(_field("building", "numberOfFloors", "Number of Floors", floors, "", conf, src))
    prefill["numberOfFloors"] = floors

    # ── Plot / Built-up Area ──
    plot_area = ai_pf.get("plotArea")
    if plot_area:
        fields.append(_field("area", "plotArea", "Plot Area", float(plot_area), "m²", "high", "AI Vision Extraction"))
        prefill["plotArea"] = float(plot_area)

    built_up = ai_pf.get("totalBuiltUpArea")
    if built_up:
        fields.append(_field("area", "totalBuiltUpArea", "Total Built-up Area", float(built_up), "m²", "high", "AI Vision Extraction"))
        prefill["totalBuiltUpArea"] = float(built_up)

    # ── TABLE TYPE 1 (PRIMARY, authoritative) ──
    if type1:
        v = type1["values"]
        conf = type1["confidence"]
        src = "Area/F.S.I. Table (Type 1) — PRIMARY"
        if "plot_area" in v and not prefill.get("plotArea"):
            fields.append(_field("area", "plotArea", "Plot Area", v["plot_area"], "m²", conf, src))
            prefill["plotArea"] = v["plot_area"]
        if "total_built_up_area" in v and not prefill.get("totalBuiltUpArea"):
            fields.append(_field("area", "totalBuiltUpArea", "Total Built-up Area", v["total_built_up_area"], "m²", conf, src))
            prefill["totalBuiltUpArea"] = v["total_built_up_area"]
        if "fsi_ratio" in v:
            fields.append(_field("area", "fsiRatio", "F.S.I. Ratio (reference)", v["fsi_ratio"], "", conf, src,
                                 note="Reference only — not a direct engine input."))

    # ── Per-floor areas ──
    floor_areas = ai_pf.get("floorAreas")
    if isinstance(floor_areas, list) and len(floor_areas) > 0 and all(isinstance(x, (int, float)) for x in floor_areas):
        areas_list = [float(x) for x in floor_areas]
        if len(areas_list) != floors:
            if len(areas_list) < floors:
                last_val = areas_list[-1] if areas_list else 100.0
                areas_list += [last_val] * (floors - len(areas_list))
            else:
                areas_list = areas_list[:floors]
        fields.append(_field("area", "floorAreas", "Floor Areas", areas_list, "m²", "high", "AI Vision Extraction"))
        prefill["floorAreas"] = areas_list
    elif prefill.get("totalBuiltUpArea"):
        tot = float(prefill["totalBuiltUpArea"])
        n = max(1, floors)
        per = round(tot / n, 2)
        fields.append(_field("area", "floorAreas", "Per-floor Areas (even split)", [per] * n, "m²", "medium",
                             "Derived: built-up ÷ floors",
                             note="Even split estimate — correct each floor from the plan if needed."))
        prefill["floorAreas"] = [per] * n
    elif prefill.get("plotArea"):
        tot = float(prefill["plotArea"])
        n = max(1, floors)
        per = round(tot / n, 2)
        fields.append(_field("area", "floorAreas", "Per-floor Areas (estimated)", [per] * n, "m²", "low",
                             "Estimated from plot area"))
        prefill["floorAreas"] = [per] * n
    else:
        prefill["floorAreas"] = [500.0] * max(1, floors)

    # ── Building height: "HEIGHT ... 22.50 M" ──
    h = ai_pf.get("buildingHeight")
    if not h:
        m = re.search(r"(?:BUILDING\s*)?HEIGHT[^0-9]{0,15}([0-9]{1,3}\.?[0-9]*)\s*M", up)
        if m:
            val = float(m.group(1))
            if 2 < val < 300:
                h = val
    if not h or float(h) <= 0:
        h = round(max(1, floors) * 3.5, 1)
        fields.append(_field("building", "buildingHeight", "Building Height (estimated)", h, "m", "low",
                             f"Derived: {floors} floors × 3.5m",
                             note="Estimated height — please confirm or enter exact height."))
    else:
        conf = "high" if ai_pf.get("buildingHeight") else "medium"
        src = "AI Vision Extraction" if ai_pf.get("buildingHeight") else "Text on plan"
        fields.append(_field("building", "buildingHeight", "Building Height", float(h), "m", conf, src))
    prefill["buildingHeight"] = float(h)

    # ── Basement ──
    basement_cnt = ai_pf.get("basementCount", 0)
    if not basement_cnt and re.search(r"\bBASEMENT\b", up):
        bm = re.search(r"(\d)\s*(?:LEVEL|LVL|NOS?)?\s*BASEMENT", up)
        basement_cnt = int(bm.group(1)) if bm else 1
    fields.append(_field("building", "basementCount", "Basement Levels", int(basement_cnt or 0), "", "medium", "Plan analysis"))
    prefill["basementCount"] = int(basement_cnt or 0)
    prefill["basementArea"] = float(ai_pf.get("basementArea", 0.0) or 0.0)

    # ── Checkboxes: kitchen / sprinklers ──
    has_kitchen = bool(ai_pf.get("hasKitchen") or re.search(r"\bKITCHEN\b", up))
    if has_kitchen:
        fields.append(_field("hazards", "hasKitchen", "Kitchen present", True, "", "medium", "Plan detection"))
    prefill["hasKitchen"] = has_kitchen

    has_sprinkler = bool(ai_pf.get("sprinklerProposed") or re.search(r"SPRINKLER", up))
    if has_sprinkler:
        fields.append(_field("hazards", "sprinklerProposed", "Sprinklers proposed", True, "", "medium", "Plan detection"))
    prefill["sprinklerProposed"] = has_sprinkler

    # ── Occupancy ──
    occ_sub = ai_pf.get("primaryOccupancy")
    if occ_sub:
        occ_sub = occ_sub.strip().upper()
        if not re.match(r"^[A-J]-\d+$", occ_sub) and len(occ_sub) == 1 and occ_sub in _GROUP_DEFAULT_SUB:
            occ_sub = _GROUP_DEFAULT_SUB[occ_sub]
        elif occ_sub.startswith("COMMERCIAL") or "COMMERCIAL" in occ_sub:
            occ_sub = "F-1"
        elif occ_sub.startswith("RESIDENTIAL") or "RESIDENTIAL" in occ_sub:
            occ_sub = "A-4"
        elif occ_sub.startswith("OFFICE") or occ_sub.startswith("BUSINESS"):
            occ_sub = "E-1"
        elif occ_sub.startswith("EDUCATIONAL") or occ_sub.startswith("SCHOOL"):
            occ_sub = "B-1"
        elif occ_sub.startswith("INDUSTRIAL"):
            occ_sub = "G-1"

    if not occ_sub and type2:
        v = type2["values"]
        conf = type2["confidence"]
        src = ("Structured Area Statement (Type 2) — PRIMARY"
               if type2.get("structured") else "Occupancy/Use Table (Type 2) — PRIMARY")
        use_txt = v.get("building_use") or v.get("declared_use") or v.get("building_subuse")
        grp = v.get("inferred_occupancy_group")
        if use_txt:
            fields.append(_field("occupancy", "declaredUse", "Declared Use / Occupancy", use_txt, "", conf, src))
        if grp:
            occ_sub = _GROUP_DEFAULT_SUB.get(grp, "F-1")

    if not occ_sub:
        if "COMMERCIAL" in up:
            occ_sub = "F-1"
        elif "RESIDENTIAL" in up:
            occ_sub = "A-4"
        elif "OFFICE" in up or "BUSINESS" in up:
            occ_sub = "E-1"
        elif "EDUCATIONAL" in up or "SCHOOL" in up:
            occ_sub = "B-1"
        elif "HOSPITAL" in up:
            occ_sub = "C-1"
        elif "INDUSTRIAL" in up:
            occ_sub = "G-1"
        elif "STORAGE" in up or "WAREHOUSE" in up:
            occ_sub = "H"

    if occ_sub:
        grp = occ_sub[0]
        fields.append(_field("occupancy", "primaryOccupancy", "Primary Occupancy (NBC)",
                             occ_sub, "", "high" if ai_pf.get("primaryOccupancy") else "medium",
                             "AI Vision Extraction" if ai_pf.get("primaryOccupancy") else "Occupancy detection",
                             note=f"Mapped to NBC group {grp} ({_GROUP_LABEL.get(grp,'')}). Adjust subdivision if needed."))
        prefill["primaryOccupancy"] = occ_sub

    if not prefill.get("primaryOccupancy"):
        warnings.append("Occupancy could not be reliably determined — please select it on the review screen.")

    return {"fields": fields, "prefill": prefill, "warnings": warnings}
