# backend/main.py
# FastAPI Application Entry Point
#
# Runs on port 8000 with CORS enabled for Next.js frontend (port 3000).
# Mounts all API routes under /api/*.

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from routes.analyze import router as analyze_router
from routes.analyze_manual import router as analyze_manual_router
from routes.analyze_simple import router as analyze_simple_router
from routes.analyze_mixed import router as analyze_mixed_router
from routes.report_pdf import router as report_pdf_router
from routes.plan import router as plan_router
from plan_reader.config import log_config_status

app = FastAPI(
    title="FireRuleX API",
    description="AI-powered fire extinguisher compliance checker (IS 2190:2024 & NBC 2016 Part IV)",
    version="0.2.0",
)

# CORS: allow Next.js frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(analyze_router)
app.include_router(analyze_manual_router)
app.include_router(analyze_simple_router)
app.include_router(analyze_mixed_router)
app.include_router(report_pdf_router)
app.include_router(plan_router)


@app.on_event("startup")
async def _log_service_status() -> None:
    # Part 2 — log each configured service's status so it can be confirmed
    # from the deployment log alone.
    log_config_status()


@app.get("/")
async def root():
    return {"status": "ok", "service": "FireRuleX API", "version": "0.2.0"}


@app.get("/api/health")
async def health_check():
    """Check the status of all API keys and services."""
    import os
    from plan_reader.config import get_plan_config

    plan_cfg = get_plan_config()

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    checks = {
        "GEMINI_API_KEY": {
            "set": bool(gemini_key),
            "masked": f"{gemini_key[:4]}...{gemini_key[-4:]}" if len(gemini_key) > 8 else ("***" if gemini_key else "NOT SET"),
        },
        "OPENAI_API_KEY": {
            "set": bool(openai_key),
            "masked": f"{openai_key[:4]}...{openai_key[-4:]}" if len(openai_key) > 8 else ("***" if openai_key else "NOT SET"),
        },
        "PLAN_AI_OCR": {
            "requested": plan_cfg["ai_ocr_requested"],
            "key_present": plan_cfg["ai_ocr_key_present"],
            "active": plan_cfg["ai_ocr_active"],
        },
    }

    # Overall status: healthy if the primary AI provider key is set
    overall = "healthy" if gemini_key else "degraded"

    return {
        "status": overall,
        "service": "FireRuleX API",
        "version": "0.2.0",
        "checks": checks,
        "message": (
            "All systems operational." if gemini_key
            else "⚠ GEMINI_API_KEY is not set. AI analysis will fail. Add it to backend/.env"
        ),
    }
