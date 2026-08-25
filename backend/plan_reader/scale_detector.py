# backend/plan_reader/scale_detector.py
# Per-drawing-block scale detection, unit inference, and column-label
# exclusion. Implements Part 4 points 1, 2, 3 and 7.
#
# KEY PRINCIPLE (from the spec, confirmed against real Indian drawings):
#   scale is PER BLOCK, not per page/file. We first find the printed
#   drawing-block titles (each acts as an anchor), then detect a scale
#   note and/or real dimension text near each block, calibrate
#   independently, and cross-check the two sources (dual-source
#   validation). Where nothing usable exists → honest fallback (no
#   precise placement for that block).

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pdf_extractor import PageData, Word

# Points-per-inch in PDF space; 1 inch = 25.4 mm
PDF_PT_PER_MM = 72.0 / 25.4

_FLOOR_BLOCK_TITLES = [
    "GROUND FLOOR PLAN", "GROUND FLOOR", "FIRST FLOOR PLAN", "SECOND FLOOR PLAN",
    "TYPICAL FLOOR PLAN", "FLOOR PLAN", "BASEMENT PLAN", "TERRACE PLAN",
    "STILT FLOOR", "PODIUM PLAN", "LOWER GROUND", "UPPER GROUND",
]
_NON_FLOOR_TITLES = [
    "SITE PLAN", "KEY PLAN", "LAYOUT PLAN", "SECTION", "ELEVATION",
    "PARKING", "LOCATION PLAN", "AREA STATEMENT",
]


@dataclass
class Block:
    id: str
    title: str
    bbox: tuple[float, float, float, float]  # x0,y0,x1,y1 (PDF pts)
    is_floor_plan: bool
    scale_note: str | None = None
    scale_ratio: float | None = None          # denominator of 1:N (paper→real)
    scale_from_note_pt_per_m: float | None = None
    scale_from_dim_pt_per_m: float | None = None
    unit: str | None = None                    # 'mm' | 'm' | 'ft'
    unit_source: str = "inferred"
    nts: bool = False
    calibrated_pt_per_m: float | None = None
    calibration_confidence: str = "low"        # high | medium | low
    calibration_source: str = "none"
    conflict: str | None = None
    has_geometry: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "bbox": list(self.bbox),
            "is_floor_plan": self.is_floor_plan, "scale_note": self.scale_note,
            "unit": self.unit, "unit_source": self.unit_source, "nts": self.nts,
            "calibrated_pt_per_m": self.calibrated_pt_per_m,
            "calibration_confidence": self.calibration_confidence,
            "calibration_source": self.calibration_source, "conflict": self.conflict,
            "has_geometry": self.has_geometry,
        }

    @staticmethod
    def from_dict(d: dict) -> "Block":
        b = Block(id=d["id"], title=d["title"], bbox=tuple(d["bbox"]),
                  is_floor_plan=d["is_floor_plan"])
        b.scale_note = d.get("scale_note")
        b.unit = d.get("unit"); b.unit_source = d.get("unit_source", "inferred")
        b.nts = d.get("nts", False)
        b.calibrated_pt_per_m = d.get("calibrated_pt_per_m")
        b.calibration_confidence = d.get("calibration_confidence", "low")
        b.calibration_source = d.get("calibration_source", "none")
        b.conflict = d.get("conflict")
        b.has_geometry = d.get("has_geometry", False)
        return b


def _parse_scale_note(s: str) -> tuple[str | None, float | None, float | None]:
    """Return (normalised_note, ratio_denominator, pt_per_m).

    Handles '1:100', '1 : 100', '1 CM = 4.00 MT', 'N.T.S'.
    """
    if not s:
        return None, None, None
    up = s.upper()
    if re.search(r"N\.?\s*T\.?\s*S", up):
        return "N.T.S.", None, None
    # 1:100 style — 1 paper unit : N real units (same unit). On paper 1
    # metre real = (1000 mm /N) mm on paper → convert mm→pt.
    m = re.search(r"1\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", up)
    if m and "CM" not in up:
        denom = float(m.group(1))
        pt_per_m = (1000.0 / denom) * PDF_PT_PER_MM
        return f"1:{int(denom) if denom.is_integer() else denom}", denom, pt_per_m
    # '1 CM = 4.00 MT' → 1 cm paper = 4 m real → 1 m real = 0.25 cm = 2.5mm paper
    m = re.search(r"1\s*CM\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*M", up)
    if m:
        meters = float(m.group(1))
        mm_paper_per_m = 10.0 / meters  # 1cm=10mm paper per `meters` real
        pt_per_m = mm_paper_per_m * PDF_PT_PER_MM
        denom = meters * 100.0  # 1 cm : meters*100 cm
        return f"1 cm = {meters:g} m", denom, pt_per_m
    return None, None, None


def detect_unit(page: PageData) -> tuple[str, str]:
    """Context-aware unit inference (Part 4 point 3).

    Returns (unit, source). An explicit sheet-wide note wins.
    """
    up = page.text.upper()
    if re.search(r"ALL\s+DIMENSIONS?\s+(?:ARE\s+)?IN\s+M(?:ETER|ETRE|T)S?\b", up):
        return "m", "explicit_note"
    if re.search(r"ALL\s+DIMENSIONS?\s+(?:ARE\s+)?IN\s+(?:MM|MILLIMET)", up):
        return "mm", "explicit_note"
    if re.search(r"ALL\s+DIMENSIONS?\s+(?:ARE\s+)?IN\s+(?:FEET|FT)", up):
        return "ft", "explicit_note"
    # feet-inch marks like 12'-0"X13'-6"
    if re.search(r"[0-9]+\s*'\s*-?\s*[0-9]*\s*\"", page.text):
        return "ft", "inferred_notation"
    return "mm", "inferred_default"


# structural column tags e.g. C5 12"X27"  or  C-12 (300X600)
_COLUMN_TAG = re.compile(r"\bC[\-\s]?\d{1,3}\b", re.IGNORECASE)
_DIM_FT_IN = re.compile(r"(\d+)\s*'\s*-?\s*(\d+)?\s*\"?\s*[xX×]\s*(\d+)\s*'\s*-?\s*(\d+)?\s*\"?")
_DIM_MM = re.compile(r"\b(\d{3,5})\s*[xX×]\s*(\d{3,5})\b")


def is_column_label(word: Word, neighbours: list[Word]) -> bool:
    """A dimension attached to a column tag (e.g. 'C5 12"X27"') is a column
    cross-section — exclude it from room/equipment calculations (point 3)."""
    if _COLUMN_TAG.search(word.text):
        return True
    for n in neighbours:
        if _COLUMN_TAG.search(n.text) and abs(n.cx - word.cx) < 40 and abs(n.cy - word.cy) < 12:
            return True
    return False


def _collect_dimension_texts(page: PageData) -> list[dict]:
    """Real printed dimension strings, EXCLUDING column cross-sections."""
    out = []
    words = page.words
    for i, w in enumerate(words):
        neigh = words[max(0, i - 3):i] + words[i + 1:i + 4]
        if is_column_label(w, neigh):
            continue
        m = _DIM_FT_IN.search(w.text)
        if m:
            ft1 = float(m.group(1)) + (float(m.group(2) or 0) / 12.0)
            meters = ft1 * 0.3048
            out.append({"word": w, "meters": meters, "raw": w.text, "kind": "ft"})
            continue
        m = _DIM_MM.search(w.text)
        if m:
            val = float(m.group(1))
            if 900 <= val <= 20000:  # plausible architectural mm room dim
                out.append({"word": w, "meters": val / 1000.0, "raw": w.text, "kind": "mm"})
    return out


def find_blocks(page: PageData) -> list[Block]:
    """Identify distinct drawing blocks on the page from their titles.

    Heuristic anchor approach: each recognised title word-run becomes a
    block; its bbox is estimated from the surrounding vector geometry.
    If no titles are found, the whole page is treated as a single block.
    """
    blocks: list[Block] = []
    text_up = page.text.upper()

    title_hits: list[tuple[str, bool, Word]] = []
    # longer titles first so "GROUND FLOOR PLAN" wins over the substrings
    # "GROUND FLOOR" / "FLOOR PLAN" that it contains.
    ordered = sorted(_FLOOR_BLOCK_TITLES + _NON_FLOOR_TITLES, key=lambda t: -len(t.split()))
    for title in ordered:
        anchor = _find_phrase_anchor(page.words, title)
        if anchor is not None:
            is_floor = title in _FLOOR_BLOCK_TITLES
            # skip if this anchor overlaps one we already accepted (a longer
            # title covering the same spot)
            if any(abs(anchor.cx - a.cx) < 60 and abs(anchor.cy - a.cy) < 20
                   for _, _, a in title_hits):
                continue
            title_hits.append((title, is_floor, anchor))

    if not title_hits:
        # single implicit block = full page geometry bbox
        bbox = _geometry_bbox(page) or (0, 0, page.width, page.height)
        b = Block(id="block-0", title="(untitled drawing)", bbox=bbox,
                  is_floor_plan=True, has_geometry=bool(page.lines))
        _calibrate_block(b, page)
        return [b]

    # de-dupe overlapping titles, keep first of each
    seen_titles = set()
    idx = 0
    for title, is_floor, anchor in title_hits:
        if title in seen_titles:
            continue
        seen_titles.add(title)
        bbox = _block_bbox_around(page, anchor)
        b = Block(
            id=f"block-{idx}",
            title=title.title(),
            bbox=bbox,
            is_floor_plan=is_floor,
            has_geometry=_bbox_has_geometry(page, bbox),
        )
        _calibrate_block(b, page, near=anchor)
        blocks.append(b)
        idx += 1
    return blocks


def _find_phrase_anchor(words: list[Word], phrase: str) -> Word | None:
    toks = phrase.split()
    n = len(toks)
    upper = [w.text.upper() for w in words]
    for i in range(len(words) - n + 1):
        if upper[i:i + n] == toks:
            # anchor = centroid of the matched run
            xs = words[i:i + n]
            x0 = min(w.x0 for w in xs); y0 = min(w.y0 for w in xs)
            x1 = max(w.x1 for w in xs); y1 = max(w.y1 for w in xs)
            return Word(x0, y0, x1, y1, phrase)
    return None


def _geometry_bbox(page: PageData) -> tuple[float, float, float, float] | None:
    if not page.lines:
        return None
    xs = [c for s in page.lines for c in (s.x0, s.x1)]
    ys = [c for s in page.lines for c in (s.y0, s.y1)]
    return (min(xs), min(ys), max(xs), max(ys))


def _block_bbox_around(page: PageData, anchor: Word) -> tuple[float, float, float, float]:
    """Grow a bbox from geometry that sits below/around the title anchor."""
    # collect line segments whose midpoint is within a reasonable region
    # of the title (titles usually sit above or below the drawing).
    region_lines = []
    for s in page.lines:
        mx = (s.x0 + s.x1) / 2
        my = (s.y0 + s.y1) / 2
        if abs(mx - anchor.cx) < page.width * 0.35 and abs(my - anchor.cy) < page.height * 0.4:
            region_lines.append(s)
    if not region_lines:
        # fallback: quadrant around anchor
        w = page.width * 0.45
        h = page.height * 0.4
        return (max(0, anchor.cx - w / 2), anchor.cy,
                min(page.width, anchor.cx + w / 2), min(page.height, anchor.cy + h))

    # Full endpoint bbox (robust baseline).
    exs = [c for s in region_lines for c in (s.x0, s.x1)]
    eys = [c for s in region_lines for c in (s.y0, s.y1)]
    fx0, fy0, fx1, fy1 = min(exs), min(eys), max(exs), max(eys)

    # Only apply the percentile trim (to reject bleed from adjacent blocks on
    # dense sheets) when there is ENOUGH geometry for it to be meaningful.
    # On sparse blocks a percentile of a handful of midpoints collapses to a
    # zero-area box, so we keep the full endpoint bbox there.
    if len(region_lines) >= 20:
        mxs = sorted((s.x0 + s.x1) / 2 for s in region_lines)
        mys = sorted((s.y0 + s.y1) / 2 for s in region_lines)

        def pct(vals, p):
            i = min(len(vals) - 1, max(0, int(p * (len(vals) - 1))))
            return vals[i]

        bx0, by0, bx1, by1 = pct(mxs, 0.08), pct(mys, 0.08), pct(mxs, 0.92), pct(mys, 0.92)
        # guard against a collapsed trim — fall back to full bbox if degenerate
        if (bx1 - bx0) < 20 or (by1 - by0) < 20:
            return (fx0, fy0, fx1, fy1)
        return (bx0, by0, bx1, by1)

    return (fx0, fy0, fx1, fy1)


def _bbox_has_geometry(page: PageData, bbox) -> bool:
    x0, y0, x1, y1 = bbox
    cnt = 0
    for s in page.lines:
        mx = (s.x0 + s.x1) / 2; my = (s.y0 + s.y1) / 2
        if x0 <= mx <= x1 and y0 <= my <= y1 and s.length > 3:
            cnt += 1
            if cnt >= 4:
                return True
    return False


def _nearest_scale_note(page: PageData, near: Word | None) -> str | None:
    # scan text for a scale token; if `near` given, prefer the closest one
    candidates = []
    for w in page.words:
        if re.search(r"1\s*[:=]\s*\d", w.text) or "N.T.S" in w.text.upper() or re.search(r"1\s*CM", w.text.upper()):
            candidates.append(w)
    # also try scanning the raw text as a whole
    if not candidates:
        m = re.search(r"(1\s*[:=]\s*[0-9.]+|1\s*CM\s*=\s*[0-9.]+\s*M[T]?|N\.?T\.?S\.?)", page.text, re.IGNORECASE)
        return m.group(1) if m else None
    if near is not None:
        candidates.sort(key=lambda w: (w.cx - near.cx) ** 2 + (w.cy - near.cy) ** 2)
    return candidates[0].text


def _calibrate_block(b: Block, page: PageData, near: Word | None = None) -> None:
    unit, unit_src = detect_unit(page)
    b.unit, b.unit_source = unit, unit_src

    note = _nearest_scale_note(page, near)
    norm, denom, pt_per_m_note = _parse_scale_note(note or "")
    b.scale_note = norm or note
    if norm == "N.T.S.":
        b.nts = True
    b.scale_ratio = denom
    b.scale_from_note_pt_per_m = pt_per_m_note

    # dimension-based calibration: pick the dim text whose length roughly
    # matches a nearby long geometry segment.
    dims = _collect_dimension_texts(page)
    pt_per_m_dim = _calibrate_from_dims(page, b, dims)
    b.scale_from_dim_pt_per_m = pt_per_m_dim

    # dual-source validation (Part 4 point 2)
    if pt_per_m_note and pt_per_m_dim:
        ratio = pt_per_m_note / pt_per_m_dim
        if 0.8 <= ratio <= 1.25:
            b.calibrated_pt_per_m = pt_per_m_note
            b.calibration_confidence = "high"
            b.calibration_source = "note+dimension agree"
        else:
            # DO NOT silently average or prefer one — surface the conflict.
            b.calibrated_pt_per_m = pt_per_m_dim
            b.calibration_confidence = "low"
            b.calibration_source = "conflict"
            b.conflict = (
                f"Printed scale note ({b.scale_note}) implies "
                f"{pt_per_m_note:.1f} pt/m but nearby dimension text implies "
                f"{pt_per_m_dim:.1f} pt/m. Please confirm the correct scale."
            )
    elif b.nts:
        # N.T.S: rely ONLY on dimension text if present
        if pt_per_m_dim:
            b.calibrated_pt_per_m = pt_per_m_dim
            b.calibration_confidence = "medium"
            b.calibration_source = "dimension_only (block marked N.T.S.)"
        else:
            b.calibrated_pt_per_m = None
            b.calibration_confidence = "low"
            b.calibration_source = "unresolved (N.T.S. and no dimension text)"
    elif pt_per_m_note:
        b.calibrated_pt_per_m = pt_per_m_note
        b.calibration_confidence = "medium"
        b.calibration_source = "scale_note_only"
    elif pt_per_m_dim:
        b.calibrated_pt_per_m = pt_per_m_dim
        b.calibration_confidence = "medium"
        b.calibration_source = "dimension_only"
    else:
        b.calibrated_pt_per_m = None
        b.calibration_confidence = "low"
        b.calibration_source = "none"


def _calibrate_from_dims(page: PageData, b: Block, dims: list[dict]) -> float | None:
    """Match dimension texts to the closest parallel geometry span to derive
    paper-points-per-real-metre. Returns None if not resolvable."""
    if not dims or not page.lines:
        return None
    x0, y0, x1, y1 = b.bbox
    samples = []
    for d in dims:
        w = d["word"]
        if not (x0 - 20 <= w.cx <= x1 + 20 and y0 - 20 <= w.cy <= y1 + 20):
            continue
        # find nearest reasonably long segment to this dimension text
        best = None
        best_dist = 1e9
        for s in page.lines:
            if s.length < 20:
                continue
            mx = (s.x0 + s.x1) / 2; my = (s.y0 + s.y1) / 2
            dist = (mx - w.cx) ** 2 + (my - w.cy) ** 2
            if dist < best_dist:
                best_dist = dist
                best = s
        if best and d["meters"] > 0.2:
            samples.append(best.length / d["meters"])
    if not samples:
        return None
    samples.sort()
    return samples[len(samples) // 2]  # median
