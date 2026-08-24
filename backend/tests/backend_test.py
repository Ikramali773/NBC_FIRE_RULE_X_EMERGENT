# Backend API regression + new-layer (plan reader) tests
# Modules covered:
#   - routes/plan.py       : /api/plan/status, /api/plan/extract, /api/plan/placement
#   - existing engine API  : /api/analyze-mixed, /api/analyze-manual, /api/occupancies,
#                            /api/reports/compliance.pdf  (no-regression)

import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL is missing")
BASE_URL = base_url.rstrip("/")

FIXTURE = Path("/app/backend/tests/_synthetic_plan.pdf")

TIMEOUT = 180


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    return s


@pytest.fixture(scope="session")
def extraction(client):
    assert FIXTURE.exists(), "synthetic fixture missing; run make_synthetic_plan.py"
    with FIXTURE.open("rb") as fh:
        r = client.post(
            f"{BASE_URL}/api/plan/extract",
            files={"file": ("_synthetic_plan.pdf", fh, "application/pdf")},
            timeout=TIMEOUT,
        )
    assert r.status_code == 200, r.text[:600]
    return r.json()


# ───────────────────────── /api/plan/status ─────────────────────────
class TestPlanStatus:
    def test_status(self, client):
        r = client.get(f"{BASE_URL}/api/plan/status", timeout=TIMEOUT)
        assert r.status_code == 200
        d = r.json()
        assert d["aiOcr"] == "disabled"
        assert d["coreExtraction"] == "enabled"
        assert d["tableDetection"] == "enabled"
        assert "fully functional with zero external services" in d["note"]


# ───────────────────────── /api/plan/extract ─────────────────────────
class TestPlanExtract:
    def test_tables_found(self, extraction):
        assert extraction["tablesFound"] == {"type1": True, "type2": True, "type3": True}

    def test_geometry_and_page_image(self, extraction):
        assert extraction["geometryAvailable"] is True
        assert extraction["planId"]
        img = extraction["pageImage"]
        assert img and img["width"] > 0 and img["height"] > 0 and len(img["base64"]) > 1000

    def test_plan_reference_metadata(self, extraction):
        ref = extraction["planReference"]
        assert ref is not None
        for k in ["application_no", "development_permission_no", "odps_inward_no",
                  "inward_date", "date_of_approval", "sheet", "scale", "approving_authority"]:
            assert k in ref and ref[k], f"missing planReference key {k}: {ref}"
        earlier = ref.get("earlier_approved_case")
        assert earlier, "earlier_approved_case missing"
        assert "ODPS/2019/004102" in str(earlier)

    def test_prefill_values(self, extraction):
        pf = extraction["prefill"]
        assert pf.get("plotArea") == 1200
        assert pf.get("totalBuiltUpArea") == 3060
        assert pf.get("numberOfFloors") == 7
        assert pf.get("buildingHeight") == 22.5
        assert pf.get("primaryOccupancy") == "A-4"
        assert pf.get("hasKitchen") is True
        assert pf.get("sprinklerProposed") is True

    def test_fields_have_confidence(self, extraction):
        fields = extraction["fields"]
        assert len(fields) > 0
        for f in fields:
            assert f["confidence"] in ("high", "medium", "low")
            assert f.get("key") and f.get("label")

    def test_dwg_graceful_degradation(self, client):
        fake = b"AC1027" + b"\x00" * 512
        r = client.post(
            f"{BASE_URL}/api/plan/extract",
            files={"file": ("fake.dwg", fake, "application/octet-stream")},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["extractionPath"] == "dwg_unsupported"
        assert d["geometryAvailable"] is False
        assert d["planId"] is None
        assert len(d["warnings"]) > 0 and d["warnings"][0].strip()


# ───────────────────────── /api/plan/placement ─────────────────────────
def _mixed_payload():
    return {
        "projectName": "TEST_Synthetic",
        "city": "Pune",
        "state": "Maharashtra",
        "buildingHeight": 22.5,
        "numberOfFloors": 7,
        "floorAreas": [437.1] * 7,
        "basementArea": 0,
        "basementCount": 0,
        "constructionType": "type12",
        "hasKitchen": True,
        "sprinklerProposed": True,
        "occupancySelection": {
            "mode": "single", "primaryOccupancy": "A-4",
            "secondaryOccupancies": [], "occupancyZones": [],
        },
    }


@pytest.fixture(scope="session")
def analysis(client):
    r = client.post(f"{BASE_URL}/api/analyze-mixed", json=_mixed_payload(), timeout=TIMEOUT)
    assert r.status_code == 200, r.text[:600]
    return r.json()


class TestPlacement:
    def test_placement_without_plan_id(self, client, analysis):
        r = client.post(f"{BASE_URL}/api/plan/placement", json={
            "planId": None, "buildingInput": analysis.get("extraction") or {},
            "analysis": analysis.get("analysis") or {},
        }, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["available"] is False
        assert d.get("reason") and len(d["reason"]) > 20
        assert isinstance(d.get("quantities"), list) and len(d["quantities"]) > 0

    def test_full_placement(self, client, extraction, analysis):
        r = client.post(f"{BASE_URL}/api/plan/placement", json={
            "planId": extraction["planId"],
            "floorLabel": "Ground Floor",
            "buildingInput": analysis.get("extraction") or {},
            "analysis": analysis.get("analysis") or {},
        }, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:600]
        d = r.json()
        assert d.get("available") is True, d.get("reason")

        # points
        types = {p["type"] for p in d["points"]}
        assert "extinguisher" in types
        assert "hose_reel" in types
        assert len(d["points"]) > 0
        for p in d["points"]:
            assert p["x"] >= 0 and p["y"] >= 0
            assert p.get("clause")

        # pipes: riser + ring
        kinds = {pp["kind"] for pp in d["pipes"]}
        assert "riser" in kinds and "ring" in kinds, kinds

        # side table / legend
        assert len(d["sideTable"]) > 0
        assert len(d["legend"]) > 0

        # calibration
        cal = d["calibration"]
        assert cal.get("scaleNote") == "1:100"
        assert 27.5 <= float(cal.get("ptPerM")) <= 29.5, cal

        assert d["sanity"]["ok"] is True

        # quantities source labels
        q = {x["equipment"]: x for x in d["quantities"]}
        assert "Portable Fire Extinguishers" in q
        assert q["Portable Fire Extinguishers"]["source"] == "Per NBC Part 4 calculation"
        assert q["Portable Fire Extinguishers"]["sourceType"] == "nbc"
        sprink = q.get("Sprinkler Heads")
        assert sprink is not None
        if sprink["sourceType"] == "nbc":
            assert sprink["source"] == "Per NBC Part 4 calculation"
        else:
            assert sprink["source"].startswith("Estimated per")
        for est_key in ("First-Aid Hose Reels", "Landing Valves"):
            if est_key in q:
                assert q[est_key]["source"].startswith("Estimated per"), q[est_key]
                assert q[est_key]["sourceType"] == "estimate"

        # image space present
        assert d["pageImage"]["width"] > 0


# ───────────────────────── No-regression: existing endpoints ─────────────────────────
class TestExistingEndpoints:
    def test_occupancies(self, client):
        r = client.get(f"{BASE_URL}/api/occupancies", timeout=TIMEOUT)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d.get("groups"), list) and len(d["groups"]) >= 5
        codes = [s["code"] for g in d["groups"] for s in g["subdivisions"]]
        assert "A-4" in codes

    def test_analyze_mixed_shape(self, analysis):
        assert "analysis" in analysis and "extraction" in analysis
        a = analysis["analysis"]
        assert isinstance(a.get("complianceItems"), list) and len(a["complianceItems"]) > 0
        assert a.get("occupancyClassification") or a.get("nbcCompliance")

    # PRE-EXISTING BUG (not caused by the new plan layer): /api/analyze-manual
    # crashes in engines/standards_engine.py:64 because nbc_compliance is None
    # (AttributeError: 'NoneType' object has no attribute
    # 'firefighting_installations') and is swallowed into a 400. Used by /confirm.
    def test_analyze_manual(self, client):
        payload = {
            "buildingName": "TEST_Manual",
            "buildingType": "A-4",
            "totalFloorArea": 1500,
            "numberOfFloors": 3,
            "floorAreas": [500, 500, 500],
            "buildingHeight": 20,
            "hasKitchen": False,
        }
        r = client.post(f"{BASE_URL}/api/analyze-manual", json=payload, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:600]
        d = r.json()
        assert "analysis" in d
        assert isinstance(d["analysis"].get("complianceItems"), list)

    def test_compliance_pdf(self, client, analysis):
        r = client.post(f"{BASE_URL}/api/reports/compliance.pdf", json={"payload": analysis}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:400]
        assert r.content[:4] == b"%PDF", r.content[:20]
        assert len(r.content) > 2000

    def test_analyze_mixed_validation_error(self, client):
        r = client.post(f"{BASE_URL}/api/analyze-mixed", json={"buildingHeight": -5}, timeout=TIMEOUT)
        assert r.status_code in (400, 422), r.status_code
