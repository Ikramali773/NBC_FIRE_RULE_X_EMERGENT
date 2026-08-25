# Iteration-3 re-test: sparse-geometry bbox regression fix + floor-page selection
# Modules covered:
#   - plan_reader/scale_detector._block_bbox_around (percentile trim guard)
#   - routes/plan.py  /api/plan/extract, /api/plan/placement
#   - routes/analyze_mixed.py /api/analyze-mixed
#   - routes/report_pdf.py /api/reports/compliance.pdf

import os
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL is missing")
BASE_URL = base_url.rstrip("/")

SAMPLES = Path("/app/backend/tests/samples")
SYNTH = Path("/app/backend/tests/_synthetic_plan.pdf")
TIMEOUT = 240

SYNTH_MIXED = {
    "projectName": "TEST_Synth A4",
    "state": "Maharashtra",
    "buildingHeight": 22.5,
    "numberOfFloors": 7,
    "floorAreas": [437] * 7,
    "constructionType": "type12",
    "hasKitchen": True,
    "sprinklerProposed": True,
    "occupancySelection": {"mode": "single", "primaryOccupancy": "A-4",
                           "secondaryOccupancies": [], "occupancyZones": []},
}

DIGIGOV_MIXED = {
    "projectName": "TEST_Digigov",
    "state": "Maharashtra",
    "buildingHeight": 15,
    "numberOfFloors": 3,
    "floorAreas": [592, 592, 592],
    "constructionType": "type12",
    "hasKitchen": True,
    "sprinklerProposed": True,
    "occupancySelection": {"mode": "single", "primaryOccupancy": "F-1",
                           "secondaryOccupancies": [], "occupancyZones": []},
}


@pytest.fixture(scope="session")
def client():
    return requests.Session()


def _extract(client, path: Path):
    assert path.exists(), f"missing {path}"
    t0 = time.time()
    with path.open("rb") as fh:
        r = client.post(f"{BASE_URL}/api/plan/extract",
                        files={"file": (path.name, fh, "application/pdf")},
                        timeout=TIMEOUT)
    elapsed = time.time() - t0
    assert r.status_code == 200, f"{path.name}: HTTP {r.status_code} in {elapsed:.1f}s -> {r.text[:500]}"
    d = r.json()
    d["_elapsed"] = elapsed
    return d


def _placement(client, plan_id, mixed):
    a = client.post(f"{BASE_URL}/api/analyze-mixed", json=mixed, timeout=TIMEOUT)
    assert a.status_code == 200, a.text[:600]
    aj = a.json()
    t0 = time.time()
    r = client.post(f"{BASE_URL}/api/plan/placement", json={
        "planId": plan_id,
        "floorLabel": "Ground Floor",
        "buildingInput": aj.get("extraction") or {},
        "analysis": aj.get("analysis") or {},
    }, timeout=TIMEOUT)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text[:600]
    d = r.json()
    d["_elapsed"] = elapsed
    return d


# ───────────── REGRESSION FIX: sparse synthetic fixture ─────────────
class TestSyntheticRegression:
    @pytest.fixture(scope="class")
    def d(self, client):
        return _extract(client, SYNTH)

    def test_geometry_available(self, d):
        print(f"\n[synthetic] {d['_elapsed']:.1f}s geometry={d.get('geometryAvailable')} "
              f"blocks={[(b['id'], b['title'], b['bbox'], b['hasGeometry']) for b in d.get('blocks') or []]}")
        assert d.get("geometryAvailable") is True, d.get("blocks")

    def test_ground_floor_block_non_degenerate(self, d):
        blocks = d.get("blocks") or []
        gf = [b for b in blocks if "ground floor" in (b.get("title") or "").lower()]
        assert gf, [b.get("title") for b in blocks]
        b = gf[0]
        x0, y0, x1, y1 = b["bbox"]
        assert (x1 - x0) > 20 and (y1 - y0) > 20, b["bbox"]
        assert b.get("hasGeometry") is True, b

    def test_no_degenerate_bbox_on_floor_blocks(self, d):
        # Non-floor blocks (e.g. 'Area Statement') can still collapse to a
        # zero-width bbox — reported as MINOR, not asserted here.
        degenerate = [b["id"] for b in (d.get("blocks") or [])
                      if (b["bbox"][2] - b["bbox"][0]) <= 0 or (b["bbox"][3] - b["bbox"][1]) <= 0]
        if degenerate:
            print(f"\n[synthetic] MINOR: degenerate bbox on non-floor blocks {degenerate}")
        for b in d.get("blocks") or []:
            if not b.get("isFloorPlan"):
                continue
            x0, y0, x1, y1 = b["bbox"]
            assert (x1 - x0) > 0 and (y1 - y0) > 0, f"degenerate bbox on {b['id']}: {b['bbox']}"

    def test_placement_available_with_tight_block(self, client, d):
        p = _placement(client, d["planId"], SYNTH_MIXED)
        assert p.get("available") is True, p.get("reason")
        img = p["pageImage"]
        bx0, by0, bx1, by1 = p["block"]["bboxPx"]
        assert bx1 > bx0 and by1 > by0, p["block"]["bboxPx"]
        frac = ((bx1 - bx0) * (by1 - by0)) / float(img["width"] * img["height"])
        print(f"\n[synthetic placement] block covers {frac*100:.1f}% of page, "
              f"points={len(p.get('points') or [])}")
        assert frac < 0.95, frac
        assert len(p.get("points") or []) > 0


# ───────────── digigov.pdf end-to-end still good ─────────────
class TestDigigovEndToEnd:
    @pytest.fixture(scope="class")
    def d(self, client):
        return _extract(client, SAMPLES / "digigov.pdf")

    def test_extract_and_clean_type3(self, d):
        print(f"\n[digigov] {d['_elapsed']:.1f}s tables={d.get('tablesFound')} "
              f"geometry={d.get('geometryAvailable')}")
        assert d.get("extractionPath") == "vector_text"
        ref = d.get("planReference") or {}
        vals = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in ref.items()}
        print(f"[digigov] planReference={vals}")
        assert str(vals.get("odps_inward_no") or "") == "ODPS/2025/120600", vals.get("odps_inward_no")
        assert "1:200" in str(vals.get("scale") or ""), vals.get("scale")

    def test_placement(self, client, d):
        p = _placement(client, d["planId"], DIGIGOV_MIXED)
        assert p.get("available") is True, p.get("reason")
        sprinklers = [x for x in p["points"] if x["type"] == "sprinkler"]
        print(f"\n[digigov placement] {p['_elapsed']:.2f}s sprinklers={len(sprinklers)} "
              f"total={len(p['points'])}")
        assert len(sprinklers) <= 250
        assert p["_elapsed"] < 3.0, p["_elapsed"]
        assert p.get("overlayNote")
        assert len(p.get("sideTable") or []) > 0
        assert len(p.get("legend") or []) > 0


# ───────────── floor-page selection: kasturba + almakka ─────────────
class TestFloorPageSelection:
    @pytest.fixture(scope="class")
    def kasturba(self, client):
        return _extract(client, SAMPLES / "kasturba.pdf")

    @pytest.fixture(scope="class")
    def almakka(self, client):
        return _extract(client, SAMPLES / "almakka.pdf")

    def test_kasturba_has_floor_block_with_geometry(self, kasturba):
        blocks = kasturba.get("blocks") or []
        print(f"\n[kasturba] geometry={kasturba.get('geometryAvailable')} "
              f"blocks={[(b['title'], b['isFloorPlan'], b['hasGeometry'], b['bbox']) for b in blocks]}")
        assert kasturba.get("geometryAvailable") is True
        floor = [b for b in blocks if b.get("isFloorPlan") and b.get("hasGeometry")]
        assert floor, [b.get("title") for b in blocks]

    def test_almakka_non_degenerate_floor_block(self, almakka):
        blocks = almakka.get("blocks") or []
        print(f"\n[almakka] geometry={almakka.get('geometryAvailable')} "
              f"blocks={[(b['title'], b['isFloorPlan'], b['hasGeometry'], b['bbox'], b.get('unit'), b.get('nts')) for b in blocks]}")
        assert almakka.get("geometryAvailable") is True
        good = [b for b in blocks
                if b.get("isFloorPlan")
                and (b["bbox"][2] - b["bbox"][0]) > 20
                and (b["bbox"][3] - b["bbox"][1]) > 20]
        assert good, [b.get("title") for b in blocks]

    def test_almakka_unit_ft_and_nts(self, almakka):
        floors = [b for b in (almakka.get("blocks") or []) if b.get("isFloorPlan")]
        assert floors
        units = {b.get("unit") for b in floors}
        ntses = {b.get("nts") for b in floors}
        print(f"\n[almakka] floor units={units} nts={ntses}")
        assert "ft" in units, units
        assert True in ntses, ntses


# ───────────── no-regression on core endpoints ─────────────
class TestCoreNoRegression:
    def test_occupancies(self, client):
        r = client.get(f"{BASE_URL}/api/occupancies", timeout=60)
        assert r.status_code == 200
        assert len(r.json()) > 0

    def test_analyze_mixed(self, client):
        r = client.post(f"{BASE_URL}/api/analyze-mixed", json={
            "projectName": "TEST_Manual A4",
            "state": "Maharashtra",
            "buildingHeight": 20,
            "numberOfFloors": 3,
            "floorAreas": [500, 500, 500],
            "constructionType": "type12",
            "occupancySelection": {"mode": "single", "primaryOccupancy": "A-4",
                                   "secondaryOccupancies": [], "occupancyZones": []},
        }, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:600]
        j = r.json()
        assert j.get("analysis"), list(j.keys())

    def test_compliance_pdf(self, client):
        a = client.post(f"{BASE_URL}/api/analyze-mixed", json=DIGIGOV_MIXED, timeout=TIMEOUT)
        assert a.status_code == 200
        r = client.post(f"{BASE_URL}/api/reports/compliance.pdf",
                        json={"payload": a.json()}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:400]
        assert r.content[:4] == b"%PDF", r.content[:20]
