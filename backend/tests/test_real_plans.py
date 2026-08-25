# Real sanctioned-drawing tests for the plan-reader layer
# Modules covered:
#   - routes/plan.py            : /api/plan/extract (real PDFs), /api/plan/placement
#   - plan_reader/table_parser  : Type-3 metadata ref() validation (no alphabetic bleed)
#   - plan_reader/scale_detector: block bbox tightness, unit inference, nts
#   - plan_reader/placement     : sprinkler marker cap + overlayNote

import os
import re
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
TIMEOUT = 240
SAMPLE_NAMES = ["kasturba.pdf", "sot.pdf", "digigov.pdf", "almakka.pdf", "hotel.pdf"]


@pytest.fixture(scope="session")
def client():
    return requests.Session()


def _extract(client, name):
    path = SAMPLES / name
    assert path.exists(), f"missing sample {path}"
    t0 = time.time()
    with path.open("rb") as fh:
        r = client.post(
            f"{BASE_URL}/api/plan/extract",
            files={"file": (name, fh, "application/pdf")},
            timeout=TIMEOUT,
        )
    elapsed = time.time() - t0
    assert r.status_code == 200, f"{name}: HTTP {r.status_code} in {elapsed:.1f}s -> {r.text[:500]}"
    d = r.json()
    d["_elapsed"] = elapsed
    return d


@pytest.fixture(scope="session")
def extractions(client):
    out = {}
    for n in SAMPLE_NAMES:
        out[n] = _extract(client, n)
    return out


# ───────────── all 5 real files must extract without crashing ─────────────
class TestRealExtractionAll:
    @pytest.mark.parametrize("name", SAMPLE_NAMES)
    def test_returns_200_vector_text(self, extractions, name):
        d = extractions[name]
        print(f"\n[{name}] {d['_elapsed']:.1f}s path={d.get('extractionPath')} "
              f"tables={d.get('tablesFound')} blocks={len(d.get('blocks') or [])} "
              f"geometry={d.get('geometryAvailable')}")
        assert d.get("extractionPath") == "vector_text", d.get("extractionPath")
        assert d.get("planId")
        assert d.get("pageImage") and d["pageImage"]["width"] > 0


# ───────────── digigov.pdf: clean Type-3, prefill, blocks ─────────────
class TestDigigov:
    @pytest.fixture(scope="class")
    def d(self, extractions):
        return extractions["digigov.pdf"]

    def test_tables_found_all_true(self, d):
        assert d["tablesFound"] == {"type1": True, "type2": True, "type3": True}, d["tablesFound"]

    def test_plan_reference_clean(self, d):
        ref = d.get("planReference")
        assert ref, "planReference missing"
        print("\nplanReference:", ref)
        assert ref.get("odps_inward_no") == "ODPS/2025/120600", ref.get("odps_inward_no")
        assert ref.get("scale") == "1:200", ref.get("scale")
        garbage = {"development", "inward", "app", "no", "date"}
        bad = []
        for k, v in ref.items():
            if isinstance(v, str) and v.strip().lower() in garbage:
                bad.append((k, v))
            # ref-like fields must not be purely alphabetic words
            if k in ("application_no", "development_permission_no", "odps_inward_no",
                     "inward_no", "sheet") and isinstance(v, str):
                if v.strip() and not re.search(r"\d", v):
                    bad.append((k, v))
        assert not bad, f"garbage alphabetic values in planReference: {bad}"

    def test_prefill_values(self, d):
        pf = d["prefill"]
        print("\nprefill:", pf)
        assert pf.get("plotArea") == pytest.approx(2229.75, rel=0.02), pf.get("plotArea")
        assert pf.get("totalBuiltUpArea") == pytest.approx(1777.36, rel=0.02), pf.get("totalBuiltUpArea")
        assert pf.get("primaryOccupancy") == "F-1", pf.get("primaryOccupancy")

    def test_blocks_scale_note(self, d):
        blocks = d.get("blocks") or []
        floor_blocks = [b for b in blocks if b.get("isFloorPlan")]
        print("\nfloor blocks:", [(b["id"], b.get("title"), b.get("scaleNote"), b.get("nts"),
                                  b.get("unit"), b.get("calibrationSource")) for b in floor_blocks])
        assert len(floor_blocks) > 1, f"expected multiple floor-plan blocks, got {len(floor_blocks)}"
        # NOTE (iteration-3): the floor-page chooser now picks page 2 (5 floor
        # titles) whose sheet scale is genuinely 1:100; the 1:200 note lives on
        # the title-block page 0 and is still reported via planReference.
        assert any(b.get("scaleNote") in ("1:100", "1:200") for b in floor_blocks), \
            [b.get("scaleNote") for b in floor_blocks]


# ───────────── almakka.pdf: feet inference + dimension_only calibration ─────────────
class TestAlmakka:
    @pytest.fixture(scope="class")
    def d(self, extractions):
        return extractions["almakka.pdf"]

    def test_feet_unit_and_dimension_only(self, d):
        blocks = [b for b in d.get("blocks") or [] if b.get("isFloorPlan")]
        print("\nalmakka blocks:", [(b["id"], b.get("unit"), b.get("unitSource"), b.get("nts"),
                                     b.get("calibrationSource"), b.get("calibrationConfidence"))
                                    for b in blocks])
        assert blocks, "no floor-plan blocks"
        ft = [b for b in blocks if b.get("unit") == "ft"]
        assert ft, f"expected a block with unit 'ft': {[b.get('unit') for b in blocks]}"
        assert any(b.get("nts") is True for b in ft), [b.get("nts") for b in ft]
        # NOTE (iteration-3): column labels like C5 12"X27" must NOT be treated
        # as room dimensions, so N.T.S. blocks now honestly report 'unresolved'
        # instead of a bogus dimension_only calibration.
        assert all(
            ("dimension_only" in (b.get("calibrationSource") or ""))
            or ("unresolved" in (b.get("calibrationSource") or ""))
            for b in ft
        ), [b.get("calibrationSource") for b in ft]


# ───────────── kasturba / sot / hotel: N.T.S. handled honestly ─────────────
class TestNtsFiles:
    @pytest.mark.parametrize("name", ["kasturba.pdf", "sot.pdf", "hotel.pdf"])
    def test_nts_and_calibration(self, extractions, name):
        d = extractions[name]
        blocks = [b for b in d.get("blocks") or [] if b.get("isFloorPlan")]
        print(f"\n[{name}] blocks:", [(b["id"], b.get("nts"), b.get("scaleNote"),
                                      b.get("calibrationConfidence"), b.get("calibrationSource"))
                                     for b in blocks])
        assert d.get("extractionPath") == "vector_text"
        assert blocks, "no floor-plan blocks"
        assert any(b.get("nts") is True for b in blocks), [b.get("nts") for b in blocks]
        for b in blocks:
            assert b.get("calibrationConfidence") in ("low", "medium", "high")
            assert (b.get("calibrationSource") or "").strip(), "calibrationSource must be honest/non-empty"


# ───────────── real placement on digigov.pdf ─────────────
DIGIGOV_MIXED = {
    "projectName": "TEST_Digigov",
    "city": "Pune",
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


class TestRealPlacement:
    @pytest.fixture(scope="class")
    def analysis(self, client):
        r = client.post(f"{BASE_URL}/api/analyze-mixed", json=DIGIGOV_MIXED, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:600]
        return r.json()

    @pytest.fixture(scope="class")
    def placement(self, client, extractions, analysis):
        t0 = time.time()
        r = client.post(f"{BASE_URL}/api/plan/placement", json={
            "planId": extractions["digigov.pdf"]["planId"],
            "floorLabel": "Ground Floor",
            "buildingInput": analysis.get("extraction") or {},
            "analysis": analysis.get("analysis") or {},
        }, timeout=TIMEOUT)
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text[:600]
        d = r.json()
        d["_elapsed"] = elapsed
        return d

    def test_available(self, placement):
        assert placement.get("available") is True, placement.get("reason")

    def test_placement_is_fast(self, placement):
        print(f"\nplacement elapsed: {placement['_elapsed']:.2f}s")
        assert placement["_elapsed"] < 3.0, f"placement took {placement['_elapsed']:.2f}s (cache miss?)"

    def test_block_bbox_is_tight_subregion(self, placement):
        img = placement["pageImage"]
        blk = placement.get("block") or {}
        bbox = blk.get("bboxPx")
        print(f"\nimage {img['width']}x{img['height']} bboxPx={bbox}")
        assert bbox and len(bbox) == 4, blk
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        assert w > 0 and h > 0
        area_frac = (w * h) / float(img["width"] * img["height"])
        print(f"bbox covers {area_frac*100:.1f}% of page")
        assert area_frac < 0.75, f"bbox is nearly the whole page ({area_frac*100:.1f}%)"

    def test_sprinkler_marker_cap(self, placement):
        sprinklers = [p for p in placement["points"] if p["type"] == "sprinkler"]
        print(f"\nsprinkler markers: {len(sprinklers)}; total points {len(placement['points'])}")
        assert len(sprinklers) <= 250, len(sprinklers)

    def test_overlay_note(self, placement):
        note = placement.get("overlayNote")
        print("\noverlayNote:", note)
        assert note and len(note) > 20, note

    def test_side_table_and_legend(self, placement):
        assert len(placement.get("sideTable") or []) > 0
        assert len(placement.get("legend") or []) > 0
