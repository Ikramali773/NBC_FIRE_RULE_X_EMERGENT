import sys, json
sys.path.insert(0, "/app/backend")
from plan_reader.pdf_extractor import PlanDocument
from plan_reader import table_parser, field_mapper
from plan_reader.scale_detector import find_blocks

FILES = {
    "KASTURBA_GANDHI": "kasturba.pdf",
    "SOT_ALL_FLOOR": "sot.pdf",
    "digigov_plan": "digigov.pdf",
    "Al_Makka_Fire": "almakka.pdf",
    "Hotel_Silver_Plate": "hotel.pdf",
}

import os
os.chdir("/app/backend/tests/samples")

for name, fn in FILES.items():
    print("=" * 70)
    print("FILE:", name, f"({fn})")
    data = open(fn, "rb").read()
    doc = PlanDocument(data, fn)
    if doc.error:
        print("  OPEN ERROR:", doc.error); continue
    print("  pages:", doc.page_count, "format:", doc.original_format)
    pages = [doc.read_page(i) for i in range(min(doc.page_count, 6))]
    full_text = "\n".join(p.text for p in pages)
    all_tables = [t for p in pages for t in p.tables]
    for p in pages:
        print(f"   page {p.index}: {p.width:.0f}x{p.height:.0f}pt textlen={len(p.text.strip())} "
              f"words={len(p.words)} lines={len(p.lines)} tables={len(p.tables)} "
              f"scanned={p.is_scanned} imgRatio={p.image_area_ratio:.2f}")
    t1 = table_parser.parse_type1_fsi(full_text, all_tables)
    t2 = table_parser.parse_type2_occupancy(full_text, all_tables)
    t3 = table_parser.parse_type3_metadata(full_text, all_tables)
    print("  TABLE TYPE 1 (FSI):", json.dumps(t1.get("values")) if t1 else "NOT FOUND")
    print("  TABLE TYPE 2 (Occ):", json.dumps(t2.get("values")) if t2 else "NOT FOUND", "| structured:", t2.get("structured") if t2 else None)
    print("  TABLE TYPE 3 (ODPS):", json.dumps(t3.get("values")) if t3 else "NOT FOUND")
    m = field_mapper.build_mapping(full_text, t1, t2)
    print("  PREFILL:", json.dumps(m["prefill"]))
    print("  WARNINGS:", m["warnings"])
    # blocks + scale on best geometry page
    best = max(pages, key=lambda p: len(p.lines))
    blocks = find_blocks(best)
    print(f"  BLOCKS on page {best.index} ({len(blocks)}):")
    for b in blocks[:8]:
        print(f"     - '{b.title}' floor={b.is_floor_plan} geom={b.has_geometry} scale={b.scale_note} "
              f"unit={b.unit}({b.unit_source}) nts={b.nts} calib={b.calibration_confidence}/{b.calibration_source} ptPerM={b.calibrated_pt_per_m}")
    doc.close()
print("=" * 70)
