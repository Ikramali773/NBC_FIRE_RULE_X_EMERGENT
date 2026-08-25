# backend/routes/analyze_mixed.py
# POST /api/analyze-mixed — Mixed-occupancy building analysis endpoint
# GET  /api/occupancies    — List all NBC occupancy codes/labels for UI
#
# Accepts a structured OccupancySelection (single or mixed) plus building
# parameters and returns a full AnalyzeResponse with normalised
# ComplianceResultItems for each fire-fighting system.

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from models import (
    BuildingInput,
    OccupancySelection,
    OccupancyZone,
    AnalyzeResponse,
    AnalyzeMeta,
    ExtractionConfidence,
)
from rule_engine import run_rule_engine

router = APIRouter()

_NBC_DATA_PATH = Path(__file__).parent.parent / "data" / "nbc_building_classification.json"
with open(_NBC_DATA_PATH, "r", encoding="utf-8") as f:
    _NBC_DATA = json.load(f)


class OccupancyZoneIn(BaseModel):
    occupancy_code: str = Field(alias="occupancyCode")
    label: str = Field(default="")
    floor_range: str | None = Field(alias="floorRange", default=None)
    area_m2: float | None = Field(alias="areaM2", default=None)

    class Config:
        populate_by_name = True


class OccupancySelectionIn(BaseModel):
    mode: str = Field(default="single")
    primary_occupancy: str | None = Field(alias="primaryOccupancy", default=None)
    secondary_occupancies: list[str] = Field(alias="secondaryOccupancies", default_factory=list)
    occupancy_zones: list[OccupancyZoneIn] = Field(alias="occupancyZones", default_factory=list)

    class Config:
        populate_by_name = True


class MixedAnalyzeInput(BaseModel):
    project_name: str = Field(default="", alias="projectName")
    state: str = Field(default="")
    city: str = Field(default="")
    building_status: str | None = Field(alias="buildingStatus", default=None)
    building_height: float = Field(gt=0, alias="buildingHeight")
    number_of_floors: int = Field(ge=1, alias="numberOfFloors")
    floor_areas: list[float] = Field(alias="floorAreas")
    basement_area: float = Field(default=0, ge=0, alias="basementArea")
    basement_count: int = Field(default=0, ge=0, alias="basementCount")
    construction_type: str | None = Field(alias="constructionType", default="type12")
    has_kitchen: bool = Field(default=False, alias="hasKitchen")
    has_flammable_liquids: bool = Field(default=False, alias="hasFlammableLiquids")
    has_flammable_gases: bool = Field(default=False, alias="hasFlammableGases")
    has_combustible_metals: bool = Field(default=False, alias="hasCombustibleMetals")
    has_electrical_hazards: bool = Field(default=False, alias="hasElectricalHazards")
    sprinkler_proposed: bool | None = Field(default=None, alias="sprinklerProposed")
    occupancy_selection: OccupancySelectionIn = Field(alias="occupancySelection")

    class Config:
        populate_by_name = True


@router.get("/api/occupancies")
async def list_occupancies() -> dict:
    """Return the full list of NBC Part 4 occupancy subdivisions grouped by group.

    Shape:
      {
        "groups": [
          { "group": "A", "label": "Residential",
            "subdivisions": [{"code": "A-1", "label": "..."}] },
          ...
        ]
      }
    """
    groups: list[dict] = []
    for group_code, group in _NBC_DATA["occupancyGroups"].items():
        subs = []
        for sub_code, sub_data in (group.get("subdivisions") or {}).items():
            subs.append({
                "code": sub_code,
                "label": sub_data.get("label", sub_code),
                "description": sub_data.get("description", ""),
                "examples": sub_data.get("examples", []),
            })
        groups.append({
            "group": group_code,
            "label": group.get("label", group_code),
            "description": group.get("description", ""),
            "subdivisions": subs,
        })
    return {"groups": groups}


@router.get("/api/occupancy-presets")
async def occupancy_presets() -> dict:
    """Return commonly-used mixed-occupancy presets."""
    return {
        "presets": [
            {"id": "res_commercial_front",
             "label": "Residential + Front Commercial",
             "primary": "A-4",
             "secondary": ["F-1"]},
            {"id": "commercial_banquet",
             "label": "Commercial + Banquet Hall",
             "primary": "F-2",
             "secondary": ["D-3"]},
            {"id": "hotel_restaurant",
             "label": "Hotel + Restaurant",
             "primary": "A-5",
             "secondary": ["D-4"]},
            {"id": "apartment_shops",
             "label": "Apartment + Shops",
             "primary": "A-4",
             "secondary": ["F-1"]},
            {"id": "office_datacenter",
             "label": "Office + Data Centre",
             "primary": "E-1",
             "secondary": ["E-3"]},
        ]
    }


@router.post("/api/analyze-mixed")
async def analyze_mixed(body: MixedAnalyzeInput):
    """Run mixed-occupancy compliance analysis and return normalised result."""
    try:
        sel = body.occupancy_selection
        if not sel.primary_occupancy and not sel.occupancy_zones:
            return JSONResponse(
                content={"error": "Select at least one occupancy or add an occupancy zone."},
                status_code=400,
            )

        # Validate floor areas
        if any(a <= 0 for a in body.floor_areas):
            return JSONResponse(
                content={"error": "All floor areas must be greater than 0."},
                status_code=400,
            )

        occupancy_zones = [
            OccupancyZone(
                occupancyCode=z.occupancy_code,
                label=z.label,
                floorRange=z.floor_range,
                areaM2=z.area_m2,
            )
            for z in sel.occupancy_zones
        ]

        occupancy_selection = OccupancySelection(
            mode=sel.mode if sel.mode in ("single", "mixed") else "single",
            primaryOccupancy=sel.primary_occupancy,
            secondaryOccupancies=sel.secondary_occupancies,
            occupancyZones=occupancy_zones,
        )

        primary = sel.primary_occupancy or (occupancy_zones[0].occupancy_code if occupancy_zones else None)
        primary_group = primary.split("-")[0] if primary and "-" in primary else primary

        total_area = sum(body.floor_areas) + (body.basement_area or 0)

        default_name = "Mixed-Occupancy Building" if sel.mode == "mixed" else (f"{primary} Building" if primary else "Untitled Building")
        building_input = BuildingInput(
            buildingName=body.project_name or default_name,
            buildingType=primary or "Mixed",
            totalFloorArea=total_area,
            numberOfFloors=len(body.floor_areas),
            floorAreas=body.floor_areas,
            buildingHeight=body.building_height,
            occupantCount=0,
            hasKitchen=body.has_kitchen,
            hasFlammableLiquids=body.has_flammable_liquids,
            hasFlammableGases=body.has_flammable_gases,
            hasCombustibleMetals=body.has_combustible_metals,
            hasElectricalHazards=body.has_electrical_hazards,
            state=body.state or None,
            projectName=body.project_name,
            city=body.city,
            buildingStatus=body.building_status,
            basementCount=body.basement_count,
            sprinklerProposed=body.sprinkler_proposed,
            occupancyGroup=primary_group,
            occupancySubdivision=primary,
            constructionType=body.construction_type,
            hasSprinklers=bool(body.sprinkler_proposed),
            basementArea=body.basement_area,
            occupancySelection=occupancy_selection,
        )

        analysis = run_rule_engine(building_input)
        analysis.analysis_method = "manual_override"

        response = AnalyzeResponse(
            extraction=building_input,
            analysis=analysis,
            confidence=ExtractionConfidence(overall="high", score=100, flags=[]),
            needsConfirmation=False,
            meta=AnalyzeMeta(
                fileName="mixed_occupancy_input",
                fileSize=0,
                fileType="application/json",
                originalFormat="json",
                wasConverted=False,
                aiProvider="none",
                analyzedAt=datetime.now(timezone.utc).isoformat(),
            ),
        )
        return JSONResponse(content=response.model_dump(by_alias=True, mode="json"))
    except Exception as err:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            content={"error": f"Mixed-occupancy analysis failed: {str(err)}"},
            status_code=400,
        )
