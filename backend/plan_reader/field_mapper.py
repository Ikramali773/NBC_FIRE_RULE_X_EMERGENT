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


def build_mapping(text: str, type1: dict | None, type2: dict | None) -> dict:
    """Return {'fields': [...], 'prefill': {...camelCase...}, 'warnings': [...]}"""
    fields: list[dict] = []
    prefill: dict = {}
    warnings: list[str] = []
    up = text.upper()

    # ── Project name (text heuristic) ──
    proj = None
    m = re.search(r"(?:NAME\s+OF\s+(?:PROJECT|BUILDING|OWNER)|PROJECT)\s*[:\-]\s*([A-Za-z0-9 ,.&'\-]{3,60})", text, re.IGNORECASE)
    if m:
        proj = m.group(1).strip()
        if proj.upper().strip(" .-") not in ("NA", "N.A", "NIL", "NONE", "-"):
            fields.append(_field("project", "projectName", "Project Name", proj, "", "medium", "Text on plan"))
            prefill["projectName"] = proj

    # ── City / State ──
    for city_kw in ["AHMEDABAD", "MUMBAI", "SURAT", "VADODARA", "RAJKOT", "PUNE", "DELHI", "BENGALURU", "CHENNAI", "HYDERABAD"]:
        if city_kw in up:
            fields.append(_field("project", "city", "City", city_kw.title(), "", "medium", "Text on plan"))
            prefill["city"] = city_kw.title()
            break

    # ── Number of floors: "G + 4", "GROUND + 7 UPPER" etc ──
    floors = None
    m = re.search(r"\bG\s*\+\s*(\d{1,2})\b", up)
    if m:
        floors = int(m.group(1)) + 1
    else:
        m = re.search(r"GROUND\s*\+\s*(\d{1,2})", up)
        if m:
            floors = int(m.group(1)) + 1
    if floors:
        fields.append(_field("building", "numberOfFloors", "Number of Floors", floors, "", "medium",
                             "Floor notation on plan (G + N)"))
        prefill["numberOfFloors"] = floors

    # ── Building height: "HEIGHT ... 22.50 M" ──
    m = re.search(r"(?:BUILDING\s*)?HEIGHT[^0-9]{0,15}([0-9]{1,3}\.?[0-9]*)\s*M", up)
    if m:
        h = float(m.group(1))
        if 2 < h < 300:
            fields.append(_field("building", "buildingHeight", "Building Height", h, "m", "medium", "Text on plan"))
            prefill["buildingHeight"] = h

    # ── Basement ──
    if re.search(r"\bBASEMENT\b", up):
        bm = re.search(r"(\d)\s*(?:LEVEL|LVL|NOS?)?\s*BASEMENT", up)
        count = int(bm.group(1)) if bm else 1
        fields.append(_field("building", "basementCount", "Basement Levels", count, "", "low",
                             "Basement keyword on plan"))
        prefill["basementCount"] = count

    # ── Checkboxes: kitchen / sprinklers ──
    has_kitchen = bool(re.search(r"\bKITCHEN\b", up))
    if has_kitchen:
        fields.append(_field("hazards", "hasKitchen", "Kitchen present", True, "", "medium", "Label on plan"))
        prefill["hasKitchen"] = True
    has_sprinkler = bool(re.search(r"SPRINKLER", up))
    if has_sprinkler:
        fields.append(_field("hazards", "sprinklerProposed", "Sprinklers proposed", True, "", "medium",
                             "Sprinkler note/legend on plan"))
        prefill["sprinklerProposed"] = True

    # ── TABLE TYPE 1 (PRIMARY, authoritative) ──
    if type1:
        v = type1["values"]
        conf = type1["confidence"]
        src = "Area/F.S.I. Table (Type 1) — PRIMARY"
        if "plot_area" in v:
            fields.append(_field("area", "plotArea", "Plot Area", v["plot_area"], "m²", conf, src))
            prefill["plotArea"] = v["plot_area"]
        if "total_built_up_area" in v:
            fields.append(_field("area", "totalBuiltUpArea", "Total Built-up Area", v["total_built_up_area"], "m²", conf, src))
            prefill["totalBuiltUpArea"] = v["total_built_up_area"]
        if "fsi_ratio" in v:
            fields.append(_field("area", "fsiRatio", "F.S.I. Ratio (reference)", v["fsi_ratio"], "", conf, src,
                                 note="Reference only — not a direct engine input."))
        # If we have built-up + floors, propose an even per-floor split as a
        # starting point (clearly flagged so the user refines it).
        if "total_built_up_area" in v and prefill.get("numberOfFloors"):
            n = int(prefill["numberOfFloors"])
            per = round(v["total_built_up_area"] / max(1, n), 1)
            fields.append(_field("area", "floorAreas", "Per-floor Areas (even split)", [per] * n, "m²", "low",
                                 "Derived: built-up ÷ floors",
                                 note="Even split estimate — correct each floor from the plan before use."))
            prefill["floorAreas"] = [per] * n

    # ── TABLE TYPE 2 (PRIMARY for occupancy) ──
    if type2:
        v = type2["values"]
        conf = type2["confidence"]
        src = ("Structured Area Statement (Type 2) — PRIMARY"
               if type2.get("structured") else "Occupancy/Use Table (Type 2) — PRIMARY")
        use_txt = v.get("building_use") or v.get("declared_use") or v.get("building_subuse")
        grp = v.get("inferred_occupancy_group")
        if use_txt:
            fields.append(_field("occupancy", "declaredUse", "Declared Use / Occupancy", use_txt, "", conf, src))
        if grp:
            sub = _GROUP_DEFAULT_SUB.get(grp, "F-1")
            fields.append(_field("occupancy", "primaryOccupancy", "Primary Occupancy (NBC)",
                                 sub, "", conf if conf != "low" else "medium", src,
                                 note=f"Mapped from '{v.get('inferred_from') or use_txt}' → NBC group {grp} "
                                      f"({_GROUP_LABEL.get(grp,'')}). Adjust subdivision if needed."))
            prefill["primaryOccupancy"] = sub

    if not prefill.get("primaryOccupancy"):
        warnings.append("Occupancy could not be reliably determined — please select it on the review screen.")
    if not prefill.get("floorAreas"):
        warnings.append("Per-floor areas were not directly readable — enter/confirm each floor area before analysis.")
    if not prefill.get("buildingHeight"):
        warnings.append("Building height was not found as text — please enter it before analysis.")

    return {"fields": fields, "prefill": prefill, "warnings": warnings}
