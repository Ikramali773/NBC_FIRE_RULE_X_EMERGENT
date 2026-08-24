# backend/plan_reader/
# NEW LAYER — building-plan file reading + equipment placement.
#
# This package is a completely separate module from the existing
# calculation engine (rule_engine.py + checkers). It NEVER imports or
# mutates engine internals. It only:
#   1. Reads uploaded plan files (PDF; DWG/DXF best-effort) and proposes
#      values for the EXISTING Manual Entry form fields (BuildingInput).
#   2. Consumes the engine's ALREADY-COMPUTED AnalysisResult (spacing,
#      counts) to suggest equipment placement on the actual plan.
#
# Communication with the engine is one-directional and read-only through
# the defined AnalyzeResponse / AnalysisResult data interface.

from .config import get_plan_config, log_config_status  # noqa: F401
