"""Generate a synthetic AMC-style sanctioned plan PDF for pipeline testing.

Since the five real sample files were not uploaded, this builds a fixture
exercising: Type1 FSI table, Type2 area statement, Type3 ODPS metadata
(incl. EARLIER APPROVED CASE), a floor-plan block with vector walls +
'SCALE 1:100' + a dimension string + a structural column tag 'C5 12"X27"'.
"""
import fitz

doc = fitz.open()
page = doc.new_page(width=842, height=595)  # A4 landscape pts

# ── Title block / approval metadata (Type 3) ──
meta = [
    "SANCTIONED BUILDING PLAN",
    "NAME OF PROJECT : SKYLINE RESIDENCY",
    "AHMEDABAD MUNICIPAL CORPORATION",
    "Application No. : CE/2023/AP/00456",
    "Development Permission No. : DP/2023/778",
    "Inward No. : ODPS/2023/014577",
    "Inward Date : 12/03/2023",
    "Date of Approval : 28/06/2023",
    "Sheet No : 1/3     SCALE 1:100",
    "Assistant Engineer, AMC (Approving Authority)",
    "EARLIER APPROVED CASE DETAIL : ODPS/2019/004102 (amalgamation)",
    "ALL DIMENSIONS ARE IN METER",
    "Building Height : 22.50 M     G + 6",
    "KITCHEN provided on each floor.  SPRINKLER system proposed.",
]
y = 30
for line in meta:
    page.insert_text((30, y), line, fontsize=9)
    y += 15

# ── Type 1 area/FSI table (as text rows) ──
t1 = [
    "PLOT AREA : 1200.00 SQ.M",
    "TOTAL BUILT UP AREA : 3060.00 SQ.M",
    "PROPOSED B.U.A : 3060.00",
    "F.S.I. RATIO : 2.55",
    "BALANCE FSI : 0.15",
    "OPEN PLOT AREA : 720.00",
]
y = 250
for line in t1:
    page.insert_text((30, y), line, fontsize=9)
    y += 14

# ── Type 2 area statement ──
t2 = [
    "AREA STATEMENT",
    "PLOT USE : RESIDENTIAL",
    "PLOT SUBUSE : APARTMENT",
    "BUILDING USE : RESIDENTIAL",
    "BUILDING SUBUSE : MULTI DWELLING",
]
y = 250
for line in t2:
    page.insert_text((320, y), line, fontsize=9)
    y += 14

# ── Floor-plan block: title + walls (vector) + dimension + column tag ──
page.insert_text((560, 250), "GROUND FLOOR PLAN", fontsize=11)
# outer walls: 30 m x 24 m at 1:100 in metres-on-paper... draw a rectangle
# whose paper size encodes 1:100 of a real 12m x 9m room region.
# At 1:100, 1 real m = 10 mm paper = 28.35 pt. 12 m -> 340 pt, 9 m -> 255 pt.
rx0, ry0 = 560, 270
w_pt, h_pt = 340, 255
rect = fitz.Rect(rx0, ry0, rx0 + w_pt, ry0 + h_pt)
page.draw_rect(rect, color=(0, 0, 0), width=1.2)
# an interior partition line
page.draw_line((rx0 + 170, ry0), (rx0 + 170, ry0 + h_pt), color=(0, 0, 0), width=0.8)
page.draw_line((rx0, ry0 + 130), (rx0 + w_pt, ry0 + 130), color=(0, 0, 0), width=0.8)
# dimension text for the 12 m width (real) -> should calibrate ~28 pt/m
page.insert_text((rx0 + 150, ry0 - 6), "12.00", fontsize=8)
# structural column cross-section label (must be EXCLUDED)
page.insert_text((rx0 + 40, ry0 + 60), 'C5 12"X27"', fontsize=7)

doc.save("/app/backend/tests/_synthetic_plan.pdf")
print("wrote /app/backend/tests/_synthetic_plan.pdf pages:", doc.page_count)
