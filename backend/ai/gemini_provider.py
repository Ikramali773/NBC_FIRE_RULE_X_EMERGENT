# backend/ai/gemini_provider.py
# Gemini 2.5 Flash Vision Provider for Floor Plan Analysis
#
# Uses Google's Generative AI SDK with structured JSON output.
# temperature=0 for maximum consistency between runs.

from __future__ import annotations

import asyncio
import json
import os
import re

import google.generativeai as genai

from models import BuildingInput

# ── System instruction ────────────────────────────────────────────────

SYSTEM_INSTRUCTION = (
    "You are an expert fire safety engineer and building surveyor with 20 years "
    "of experience analyzing floor plans per Indian standards (IS 2190:2024, NBC 2016 Part IV). "
    "You produce precise, deterministic building metadata from floor plan images. "
    "You never guess — you estimate methodically using dimensional reasoning and visual cues."
)

# ── Extraction prompt ─────────────────────────────────────────────────

EXTRACTION_PROMPT = """Analyze this building floor plan image and extract building metadata for IS 2190:2024 fire extinguisher compliance and NBC 2016 Part IV checking.

## STEP 1: DIMENSIONAL REASONING (do this first)

Before extracting any values, systematically analyze the image:

1. **Look for scale indicators**: dimension lines, scale bars, grid markings, or labeled dimensions on walls/rooms.
2. **If no explicit dimensions**: use these reference anchors to estimate:
   - Standard single door width: ~0.9m
   - Standard double door width: ~1.5m
   - Standard corridor width: ~1.5–2.0m
   - Standard desk: ~1.5m × 0.75m
   - Standard parking space: ~2.5m × 5.0m
   - Typical toilet stall: ~1.0m × 1.5m
   - Standard office room: ~12–20m²
   - Standard bedroom: ~12–15m²
   - Standard classroom: ~50–60m²
3. **Count rooms and estimate areas** for each identifiable space.
4. **Sum room areas** to get total floor area — do NOT wildly guess a round number.
5. **Identify floor count**: look for floor labels (Ground, First, Second), staircase indicators, or separate plan views per floor.

## STEP 2: ROOM-TYPE → FEATURE MAPPING

Scan ALL room labels/annotations in the plan. Map them to building features using this table:

| Room Labels / Keywords | Feature to Set |
|---|---|
| Kitchen, Pantry, Canteen, Cafeteria, Food Court | hasKitchen = true; estimate cookingAreaM2 |
| Server Room, UPS Room, Electrical Panel, Switchgear, DB Room, MCC Room | hasElectricalHazards = true |
| Chemical Store, Paint Store, Fuel Store, Generator Room with fuel | hasFlammableLiquids = true; estimate litres |
| Gas Bank, LPG Store, Gas Manifold | hasFlammableGases = true; estimate litres |
| Workshop (metalworking), Foundry, Welding Bay | hasCombustibleMetals = true |
| Sprinkler riser, Sprinkler zone labels, Sprinkler heads in legend | hasSprinklers = true |

If a room type is NOT visible anywhere in the plan, set the corresponding boolean to **false** and the numeric value to **0**.

## STEP 3: OCCUPANCY CLASSIFICATION (NBC 2016 Part IV Section 3.1)

Classify the building into the CORRECT group based on its PRIMARY use:

| Group | Use | Common Plan Indicators | Typical Subdivisions |
|---|---|---|---|
| A – Residential | Living/sleeping quarters | Bedrooms, apartments, dwelling units | A-1 (lodging ≤40), A-4 (apartments), A-5 (hotels >40) |
| B – Educational | Teaching/training | Classrooms, labs, lecture halls | B-1 (≤100 students), B-2 (>100 students) |
| C – Institutional | Medical/detention | Patient rooms, wards, cells | C-1 (hospitals), C-2 (nursing), C-3 (prisons) |
| D – Assembly | ≥50 persons gather | Auditoriums, theaters, sports | D-1 (theater >1000), D-4 (hall <300), D-5 (outdoor) |
| E – Business | Offices/professional | Office rooms, conference rooms, cubicles | E-1 (offices/banks), E-2 (labs), E-3 (data centers) |
| F – Mercantile | Retail/trade | Shops, display areas, cash counters | F-1 (retail ≤500m²), F-2 (retail >500m²) |
| G – Industrial | Manufacturing | Production floors, assembly lines, machines | G-1 (low hazard), G-2 (moderate), G-3 (high hazard) |
| H – Storage | Warehousing | Racking, loading docks, storage bays | H |
| J – Hazardous | Explosive/toxic | Special containment, blast walls | J |

**If the plan shows mostly offices/cubicles → E-1. Hotel rooms → A-5. Hospital wards → C-1.**

## STEP 4: CONSTRUCTION TYPE

- **type12** (fire-resistive/non-combustible): RCC frame, steel frame, concrete walls, multi-story buildings. **Default for plans showing concrete/RCC structure.**
- **type34** (ordinary/wood-frame): Load-bearing brick/stone walls, timber frame, single-story sheds. Only use if timber or lightweight framing is clearly visible.

## EXTRACTION RULES

1. Determine buildingType naturally based on the plan (e.g., 'Hospital', 'Office', 'Residential', 'School', 'Mall', 'Factory', 'Warehouse').
2. Estimate occupantCount: 1 person per 10m² for offices, 1 per 3m² for assembly, 1 per 15m² for residential.
3. Estimate buildingHeight: numberOfFloors × 3.5m unless dimensions are visible.
4. floorAreas array MUST have exactly numberOfFloors entries.
5. totalFloorArea MUST equal the sum of floorAreas array.
6. Use 0 for numeric values ONLY if you truly cannot determine them — prefer a reasonable estimate over zero.
7. buildingName: use any title/label visible on the plan. If none, describe as "Unnamed [type] Building".

Return a JSON object with these exact fields:
{
  "buildingName": "string",
  "buildingType": "string",
  "totalFloorArea": number,
  "numberOfFloors": number,
  "floorAreas": [number],
  "buildingHeight": number,
  "occupantCount": number,
  "hasKitchen": boolean,
  "cookingAreaM2": number,
  "hasFlammableLiquids": boolean,
  "flammableLiquidsLitres": number,
  "hasFlammableGases": boolean,
  "flammableGasesLitres": number,
  "hasCombustibleMetals": boolean,
  "hasElectricalHazards": boolean,
  "occupancyGroup": "A"|"B"|"C"|"D"|"E"|"F"|"G"|"H"|"J",
  "occupancySubdivision": "string",
  "constructionType": "type12"|"type34",
  "hasSprinklers": boolean
}"""


class GeminiProvider:
    name = "gemini-3.6-flash"

    def __init__(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is required")
        genai.configure(api_key=api_key)

    async def analyze_floor_plan(
        self, documents: list[dict]
    ) -> dict:
        """
        documents: list of {"data": base64_str, "mime_type": str}
        Returns {"success": bool, "data": BuildingInput|None, "raw_response": str, "provider": str, "error": str|None}
        """
        MAX_RETRIES = 2
        last_error = ""

        print(f"[Gemini] Processing {len(documents)} documents...")

        for attempt in range(MAX_RETRIES + 1):
            try:
                model = genai.GenerativeModel(
                    model_name="gemini-3.6-flash",
                    system_instruction=SYSTEM_INSTRUCTION,
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json",
                        temperature=0,
                    ),
                )

                # Build content parts
                parts = [EXTRACTION_PROMPT]
                for doc in documents:
                    parts.append({
                        "mime_type": doc["mime_type"],
                        "data": doc["data"],
                    })

                response = await model.generate_content_async(parts)

                text = ""
                try:
                    text = response.text
                except Exception:
                    finish_reason = ""
                    if response.candidates:
                        finish_reason = str(response.candidates[0].finish_reason)
                    raise RuntimeError(
                        f"Gemini blocked response or returned non-text. Reason: {finish_reason}"
                    )

                if not text:
                    return {
                        "success": False,
                        "data": None,
                        "raw_response": "",
                        "provider": self.name,
                        "error": "Gemini returned empty response.",
                    }

                clean_text = text.strip()
                if clean_text.startswith("```"):
                    match = re.match(r"```(?:json)?\n([\s\S]*?)\n```", clean_text)
                    if match:
                        clean_text = match.group(1)
                    else:
                        clean_text = re.sub(r"^```[a-z]*\n", "", clean_text)
                        clean_text = re.sub(r"\n```$", "", clean_text)

                try:
                    parsed_dict = json.loads(clean_text)
                except json.JSONDecodeError:
                    print(f"[Gemini] JSON Parse Error. Raw text was: {text}")
                    raise RuntimeError("Failed to parse Gemini output as JSON.")

                parsed = BuildingInput(**parsed_dict)

                # ── Post-processing: enforce consistency ──

                if not parsed.floor_areas or len(parsed.floor_areas) == 0:
                    parsed.floor_areas = [parsed.total_floor_area or 0]
                    parsed.number_of_floors = 1

                if len(parsed.floor_areas) != parsed.number_of_floors:
                    parsed.number_of_floors = len(parsed.floor_areas)

                floor_sum = sum(parsed.floor_areas)
                if floor_sum > 0 and abs(parsed.total_floor_area - floor_sum) / floor_sum > 0.05:
                    parsed.total_floor_area = floor_sum

                if not parsed.occupant_count or parsed.occupant_count <= 0:
                    density_factor = (
                        3 if parsed.occupancy_group == "D"
                        else 15 if parsed.occupancy_group == "A"
                        else 10
                    )
                    parsed.occupant_count = int(
                        (parsed.total_floor_area / density_factor) + 0.5
                    )

                if not parsed.building_height or parsed.building_height <= 0:
                    parsed.building_height = parsed.number_of_floors * 3.5

                if parsed.occupancy_group and parsed.occupancy_subdivision:
                    if not parsed.occupancy_subdivision.startswith(parsed.occupancy_group):
                        parsed.occupancy_subdivision = f"{parsed.occupancy_group}-1"

                if not parsed.construction_type:
                    parsed.construction_type = "type12"

                return {
                    "success": True,
                    "data": parsed,
                    "raw_response": text,
                    "provider": self.name,
                }

            except Exception as err:
                message = str(err)
                print(f"[Gemini] Error on attempt {attempt + 1}: {message}")
                last_error = message

                if ("429" in message or "503" in message) and attempt < MAX_RETRIES:
                    retry_match = re.search(r"retry in (\d+)", message, re.IGNORECASE)
                    wait_seconds = (
                        int(retry_match.group(1)) + 2
                        if retry_match
                        else (attempt + 1) * 10
                    )
                    print(
                        f"[Gemini] Retrying in {wait_seconds}s (attempt {attempt + 1}/{MAX_RETRIES})..."
                    )
                    await asyncio.sleep(wait_seconds)
                    continue

                break

        print(f"[Gemini] All attempts failed. Return error to client: {last_error}")
        return {
            "success": False,
            "data": None,
            "raw_response": "",
            "provider": self.name,
            "error": last_error,
        }
