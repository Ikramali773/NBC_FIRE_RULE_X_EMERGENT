# backend/plan_reader/config.py
# Configuration for the plan-reading layer.
#
# COST DISCIPLINE: every external service is OPTIONAL and OFF by default.
# The whole layer works fully with zero services configured — it just
# degrades from "AI-assisted OCR on scanned files" to "vector-text only,
# honestly report what isn't readable".
#
# Env vars (all optional):
#   PLAN_ENABLE_AI_OCR   "true" to allow AI-vision OCR fallback on scanned
#                        pages. Default: off.
#   EMERGENT_LLM_KEY     Universal key powering the optional AI-vision OCR
#                        (Gemini). Free-tier compatible. If absent, AI OCR
#                        stays disabled even if PLAN_ENABLE_AI_OCR=true.
#   PLAN_RENDER_ZOOM     Pixmap render zoom for the in-app plan viewer.
#                        Default 2.0.

import os


def _as_bool(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def get_plan_config() -> dict:
    key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("EMERGENT_LLM_KEY")
        or os.environ.get("PLAN_AI_OCR_KEY")
    )
    enable_env = os.environ.get("PLAN_ENABLE_AI_OCR")
    if enable_env is not None:
        enable_ai = _as_bool(enable_env)
    else:
        enable_ai = bool(key)

    return {
        "ai_ocr_requested": enable_ai,
        "ai_ocr_key_present": bool(key),
        "ai_ocr_active": enable_ai and bool(key),
        "ai_ocr_key": key,
        "render_zoom": float(os.environ.get("PLAN_RENDER_ZOOM", "2.0") or 2.0),
    }


def log_config_status() -> None:
    """Print each configured service's status on startup (Part 2)."""
    cfg = get_plan_config()
    print("----------------------------------------------")
    print("[plan_reader] Building-Plan Reading layer - service status")
    print(f"[plan_reader]   Core PDF/vector extraction (PyMuPDF) : ENABLED (zero-cost, always on)")
    print(f"[plan_reader]   Local table detection                : ENABLED (zero-cost, always on)")
    if cfg["ai_ocr_active"]:
        status = "ENABLED (AI-vision fallback for scanned files)"
    elif cfg["ai_ocr_requested"] and not cfg["ai_ocr_key_present"]:
        status = "DISABLED (PLAN_ENABLE_AI_OCR set but no EMERGENT_LLM_KEY)"
    elif cfg["ai_ocr_key_present"] and not cfg["ai_ocr_requested"]:
        status = "DISABLED (key present but PLAN_ENABLE_AI_OCR not set)"
    else:
        status = "DISABLED (not configured - vector-text-only mode)"
    print(f"[plan_reader]   Optional AI-vision OCR (Gemini)      : {status}")
    print(f"[plan_reader]   Viewer render zoom                   : {cfg['render_zoom']}x")
    print("----------------------------------------------")
