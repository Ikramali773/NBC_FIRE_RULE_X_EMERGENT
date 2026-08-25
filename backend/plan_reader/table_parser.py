# backend/plan_reader/table_parser.py
# Recognises the three Indian sanctioned-plan table patterns from the
# extracted text + tables. Pure pattern-matching; no calculation logic.
#
#   TABLE TYPE 1 — Plot / Built-up Area / F.S.I.
#   TABLE TYPE 2 — Occupancy / Use (incl. structured Area Statement)
#   TABLE TYPE 3 — Sanctioned-Plan Reference / Approval Metadata (ODPS)
#
# Each parser returns a dict with the values it found plus a per-field
# confidence. Nothing here ever feeds the engine directly — the caller
# (field_mapper) decides how values map to form fields.

from __future__ import annotations

import re

_NUM = r"([0-9][0-9,]*\.?[0-9]*)"


def _num(s: str) -> float | None:
    if not s:
        return None
    m = re.search(_NUM, s.replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _flatten_tables(tables: list[list[list[str]]]) -> str:
    out = []
    for t in tables:
        for row in t:
            out.append(" | ".join(row))
    return "\n".join(out)


# ── TABLE TYPE 1 — Plot / Built-up / FSI ─────────────────────────


def parse_type1_fsi(text: str, tables: list[list[list[str]]]) -> dict | None:
    hay = (text + "\n" + _flatten_tables(tables))
    up = hay.upper()
    signals = ["F.S.I", "FSI", "PLOT AREA", "BUILT UP AREA", "BUILT-UP AREA", "BALANCE FSI", "PROPOSED B.U.A"]
    if not any(s in up for s in signals):
        return None

    def grab(patterns: list[str]) -> float | None:
        for p in patterns:
            m = re.search(p, hay, re.IGNORECASE)
            if m:
                v = _num(m.group(1))
                if v is not None:
                    return v
        return None

    plot_area = grab([r"PLOT\s*AREA[^0-9]{0,20}" + _NUM, r"AREA\s*OF\s*PLOT[^0-9]{0,20}" + _NUM])
    built_up = grab([
        r"TOTAL\s*BUILT[\s\-]*UP\s*AREA[^0-9]{0,20}" + _NUM,
        r"PROPOSED\s*B\.?U\.?A[^0-9]{0,20}" + _NUM,
        r"BUILT[\s\-]*UP\s*AREA[^0-9]{0,20}" + _NUM,
    ])
    fsi_ratio = grab([r"F\.?S\.?I\.?\s*(?:RATIO|CONSUMED|PROPOSED)?[^0-9]{0,12}([0-9]\.[0-9]+)"])
    balance_fsi = grab([r"BALANCE\s*F\.?S\.?I[^0-9]{0,20}" + _NUM])
    open_area = grab([r"OPEN\s*(?:PLOT\s*)?AREA[^0-9]{0,20}" + _NUM])

    found = {k: v for k, v in {
        "plot_area": plot_area,
        "total_built_up_area": built_up,
        "fsi_ratio": fsi_ratio,
        "balance_fsi": balance_fsi,
        "open_plot_area": open_area,
    }.items() if v is not None}

    if not found:
        return None
    # confidence: high if from a real table, medium if from loose text
    from_table = _flatten_tables(tables) and any(s in _flatten_tables(tables).upper() for s in signals)
    return {"values": found, "confidence": "high" if from_table else "medium", "raw_signals": [s for s in signals if s in up]}


# ── TABLE TYPE 2 — Occupancy / Use / Area Statement ──────────────

_OCC_KEYWORDS = {
    "RESIDENTIAL": "A", "APARTMENT": "A", "DWELLING": "A", "FLAT": "A", "HOTEL": "A",
    "EDUCATIONAL": "B", "SCHOOL": "B", "COLLEGE": "B",
    "INSTITUTIONAL": "C", "HOSPITAL": "C", "NURSING": "C",
    "ASSEMBLY": "D", "BANQUET": "D", "AUDITORIUM": "D", "CINEMA": "D", "RESTAURANT": "D",
    "BUSINESS": "E", "OFFICE": "E", "IT": "E",
    "MERCANTILE": "F", "SHOP": "F", "MALL": "F", "COMMERCIAL": "F", "MARKET": "F",
    "INDUSTRIAL": "G", "FACTORY": "G",
    "STORAGE": "H", "WAREHOUSE": "H",
    "HAZARDOUS": "J",
}


def parse_type2_occupancy(text: str, tables: list[list[list[str]]]) -> dict | None:
    hay = (text + "\n" + _flatten_tables(tables))
    up = hay.upper()
    structured = "AREA STATEMENT" in up or ("PLOT USE" in up and "BUILDING USE" in up)
    signals = ["AREA STATEMENT", "PLOT USE", "PLOT SUBUSE", "BUILDING USE", "BUILDING SUBUSE", "OCCUPANCY", "USE OF BUILDING"]
    if not any(s in up for s in signals) and not structured:
        # fall back to keyword scan
        pass

    def grab(label: str) -> str | None:
        m = re.search(label + r"[^A-Za-z0-9]{0,6}([A-Za-z][A-Za-z /&\-]{2,40})", hay, re.IGNORECASE)
        return m.group(1).strip() if m else None

    plot_use = grab(r"PLOT\s*USE")
    plot_subuse = grab(r"PLOT\s*SUB\s*USE")
    building_use = grab(r"BUILDING\s*USE")
    building_subuse = grab(r"BUILDING\s*SUB\s*USE")
    declared_use = grab(r"USE\s*OF\s*BUILDING") or grab(r"OCCUPANCY")

    # infer NBC group from any use string
    inferred_group = None
    inferred_source = None
    for source_val in (building_use, building_subuse, declared_use, plot_use, up):
        if not source_val:
            continue
        sv = source_val.upper()
        for kw, grp in _OCC_KEYWORDS.items():
            if kw in sv:
                inferred_group = grp
                inferred_source = kw.title()
                break
        if inferred_group:
            break

    found = {k: v for k, v in {
        "plot_use": plot_use,
        "plot_subuse": plot_subuse,
        "building_use": building_use,
        "building_subuse": building_subuse,
        "declared_use": declared_use,
        "inferred_occupancy_group": inferred_group,
        "inferred_from": inferred_source,
    }.items() if v}

    if not found:
        return None
    return {
        "values": found,
        "structured": structured,
        "confidence": "high" if structured else ("medium" if (building_use or declared_use) else "low"),
    }


# ── TABLE TYPE 3 — Sanctioned Plan Reference / Approval Metadata ──


def parse_type3_metadata(text: str, tables: list[list[list[str]]]) -> dict | None:
    hay = (text + "\n" + _flatten_tables(tables))

    def one(pattern: str) -> str | None:
        m = re.search(pattern, hay, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def ref(pattern: str) -> str | None:
        """Like one(), but only accept values that look like a real reference
        number (contain a digit or a '/'). Rejects header-word bleed such as
        'Development' / 'INWARD' / 'APP' picked up from adjacent columns."""
        val = one(pattern)
        if not val:
            return None
        val = val.strip(" .:;-)")
        if not re.search(r"[0-9/]", val) or len(val) < 3:
            return None
        return val

    odps_all = re.findall(r"ODPS\s*/\s*\d{4}\s*/\s*\d{3,7}", hay, re.IGNORECASE)
    odps_all = [re.sub(r"\s+", "", x).upper() for x in odps_all]

    application_no = ref(r"APPLICATION\s*(?:NO|NUMBER)\.?\s*[:\-]?\s*([A-Za-z0-9/\-]+)")
    dev_permission = ref(r"DEVELOPMENT\s*PERMISSION\s*(?:NO|NUMBER)?\.?\s*[:\-]?\s*([A-Za-z0-9/\-]+)")
    inward_no = ref(r"INWARD\s*(?:NO|NUMBER)\.?\s*[:\-]?\s*([A-Za-z0-9/\-]+)")
    inward_date = one(r"INWARD\s*DATE\s*[:\-]?\s*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})")
    approval_date = one(r"(?:DATE\s*OF\s*APPROVAL|APPROVAL\s*DATE|SANCTION\s*DATE)\s*[:\-]?\s*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4})")
    sheet = one(r"SHEET\s*(?:NO)?\.?\s*[:\-]?\s*(\d+\s*/\s*\d+)")
    scale = one(r"SCALE\s*[:\-]?\s*(1\s*[:=]\s*[0-9.]+|1\s*CM\s*=\s*[0-9.]+\s*M[T]?)")
    if scale:
        scale = scale.strip(" .:;-)")
    authority = one(r"((?:ASSISTANT\s+ENGINEER|EXECUTIVE\s+ENGINEER|CITY\s+ENGINEER|COMPETENT\s+AUTHORITY|TOWN\s+PLANNER)[^\n]{0,40})")

    # EARLIER APPROVED CASE — only meaningful if it actually cites a prior ref
    earlier = None
    em = re.search(r"EARLIER\s*APPROVED\s*CASE[^\n:]*:?\s*([^\n]{0,120})", hay, re.IGNORECASE)
    if em:
        block = em.group(1)
        prior_odps = re.findall(r"ODPS\s*/\s*\d{4}\s*/\s*\d{3,7}", block, re.IGNORECASE)
        prior_generic = re.findall(r"\b[A-Z]{2,}/\d{2,4}/\d{2,7}\b", block)
        if prior_odps or prior_generic:
            earlier = {
                "raw": block.strip()[:120],
                "odps_refs": [re.sub(r"\s+", "", x).upper() for x in prior_odps],
            }

    # inward_no often IS the odps number
    if not inward_no and odps_all:
        inward_no = odps_all[0]

    odps_inward = inward_no if (inward_no and "ODPS" in (inward_no or "").upper()) else (odps_all[0] if odps_all else None)
    values = {}
    if application_no:
        values["application_no"] = application_no
    if dev_permission:
        values["development_permission_no"] = dev_permission
    if odps_inward:
        values["odps_inward_no"] = odps_inward
    # only surface inward_no separately when it is distinct from the ODPS ref
    if inward_no and inward_no != odps_inward:
        values["inward_no"] = inward_no
    for k, v in {
        "inward_date": inward_date,
        "date_of_approval": approval_date,
        "sheet": sheet,
        "scale": scale,
        "approving_authority": authority,
    }.items():
        if v:
            values[k] = v

    if earlier and (earlier["odps_refs"] or earlier["raw"]):
        values["earlier_approved_case"] = earlier

    if not values:
        return None
    return {"values": values, "confidence": "high" if (odps_all or application_no or dev_permission) else "medium"}
