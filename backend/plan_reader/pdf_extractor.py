# backend/plan_reader/pdf_extractor.py
# Low-level PDF/geometry extraction using PyMuPDF (fitz) — 100% zero-cost,
# no external service, no system dependency beyond the already-installed
# PyMuPDF wheel.
#
# Responsibilities (mechanical only — no domain logic):
#   - open a document from bytes (PDF; DXF/DWG detection)
#   - per page: words with coordinates, full text, vector line segments,
#     detected tables, scanned-vs-vector classification
#   - render a page to a PNG (base64) for the in-app viewer

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class LineSeg:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def length(self) -> float:
        return ((self.x1 - self.x0) ** 2 + (self.y1 - self.y0) ** 2) ** 0.5


@dataclass
class PageData:
    index: int
    width: float
    height: float
    text: str
    words: list[Word] = field(default_factory=list)
    lines: list[LineSeg] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    is_scanned: bool = False
    image_area_ratio: float = 0.0


class PlanDocument:
    def __init__(self, data: bytes, filename: str):
        self.filename = filename
        self.error: Optional[str] = None
        self.doc: Optional[fitz.Document] = None
        self.original_format = _detect_format(filename, data)

        if self.original_format == "dwg":
            # True DWG is a proprietary binary CAD format. Reading it
            # reliably needs an external converter (ODA/LibreDWG) which is
            # NOT installed and is not zero-cost to bundle. Degrade
            # gracefully and honestly rather than guessing.
            self.error = (
                "DWG is a binary CAD format that requires an external "
                "converter (e.g. ODA File Converter → DXF/PDF), which is "
                "not configured. Please export the plan to PDF (or DXF) "
                "and re-upload. All other features remain available."
            )
            return

        try:
            open_kwargs = {}
            if self.original_format in ("pdf", "dxf"):
                open_kwargs["filetype"] = self.original_format
            self.doc = fitz.open(stream=data, **open_kwargs)
        except Exception as exc:  # pragma: no cover - defensive
            self.error = f"Could not open file: {exc}"

    # ── lifecycle ────────────────────────────────────────────────
    def close(self) -> None:
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass

    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.doc else 0

    # ── extraction ───────────────────────────────────────────────
    def read_page(self, index: int) -> PageData:
        page = self.doc[index]
        rect = page.rect
        text = page.get_text("text") or ""

        words: list[Word] = []
        for w in page.get_text("words"):
            # w = (x0, y0, x1, y1, "word", block, line, word_no)
            txt = (w[4] or "").strip()
            if txt:
                words.append(Word(w[0], w[1], w[2], w[3], txt))

        lines = _extract_lines(page)
        tables = _extract_tables(page)

        # scanned detection: little/no extractable text + large raster image
        image_area = 0.0
        try:
            for img in page.get_image_info():
                bbox = img.get("bbox")
                if bbox:
                    image_area += max(0.0, (bbox[2] - bbox[0])) * max(0.0, (bbox[3] - bbox[1]))
        except Exception:
            pass
        page_area = max(1.0, rect.width * rect.height)
        image_ratio = min(1.0, image_area / page_area)
        is_scanned = len(text.strip()) < 40 and image_ratio > 0.4

        return PageData(
            index=index,
            width=rect.width,
            height=rect.height,
            text=text,
            words=words,
            lines=lines,
            tables=tables,
            is_scanned=is_scanned,
            image_area_ratio=image_ratio,
        )

    def render_png(self, index: int, zoom: float = 2.0) -> dict:
        page = self.doc[index]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        png = pix.tobytes("png")
        return {
            "base64": base64.b64encode(png).decode("utf-8"),
            "width": pix.width,
            "height": pix.height,
            "zoom": zoom,
        }


# ── helpers ──────────────────────────────────────────────────────


def _detect_format(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    head = data[:512]
    if name.endswith(".dwg") or head[:4] in (b"AC10", b"AC11", b"AC12"):
        return "dwg"
    if head[:4] == b"AC10":
        return "dwg"
    if name.endswith(".dxf") or b"SECTION" in head[:64] and b"HEADER" in data[:2048]:
        return "dxf"
    if head[:5] == b"%PDF-" or name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".png", ".jpg", ".jpeg")) or head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image"
    return "pdf"


def _extract_lines(page: "fitz.Page") -> list[LineSeg]:
    """Pull straight line segments from the page's vector drawings."""
    segs: list[LineSeg] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return segs
    for d in drawings:
        for item in d.get("items", []):
            op = item[0]
            if op == "l":  # line: ("l", p1, p2)
                p1, p2 = item[1], item[2]
                segs.append(LineSeg(p1.x, p1.y, p2.x, p2.y))
            elif op == "re":  # rectangle → 4 edges
                r = item[1]
                segs.append(LineSeg(r.x0, r.y0, r.x1, r.y0))
                segs.append(LineSeg(r.x1, r.y0, r.x1, r.y1))
                segs.append(LineSeg(r.x1, r.y1, r.x0, r.y1))
                segs.append(LineSeg(r.x0, r.y1, r.x0, r.y0))
    return segs


def _extract_tables(page: "fitz.Page") -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    try:
        found = page.find_tables()
    except Exception:
        return tables
    for t in getattr(found, "tables", []) or []:
        try:
            rows = t.extract()
        except Exception:
            continue
        clean = [[(c or "").strip() for c in row] for row in rows if any((c or "").strip() for c in row)]
        if clean:
            tables.append(clean)
    return tables
