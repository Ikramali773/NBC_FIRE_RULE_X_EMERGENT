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
