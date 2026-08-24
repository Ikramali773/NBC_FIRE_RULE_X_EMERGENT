# backend/plan_reader/ocr.py
# OPTIONAL AI-vision OCR fallback for scanned/photographed plans.
#
# COST DISCIPLINE: this is OFF by default. It only runs when BOTH
# PLAN_ENABLE_AI_OCR=true AND an EMERGENT_LLM_KEY is configured. With
# nothing configured the whole app still works — it just can't read text
# off a purely raster/scanned sheet, and says so honestly.
#
# Uses the emergentintegrations universal-key client (Gemini vision).

from __future__ import annotations

from .config import get_plan_config


async def ocr_page_png(png_b64: str) -> str | None:
    """Return OCR'd plain text for a rendered page image, or None if AI OCR
    is unavailable/disabled/failed. Never raises."""
    cfg = get_plan_config()
    if not cfg["ai_ocr_active"]:
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

        chat = LlmChat(
            api_key=cfg["ai_ocr_key"],
            session_id="plan-ocr",
            system_message=(
                "You are an OCR engine for Indian sanctioned building plans. "
                "Transcribe ALL visible text verbatim, including table cells, "
                "area statements, scale notes, dimension strings and approval "
                "metadata. Output plain text only, no commentary."
            ),
        ).with_model("gemini", "gemini-3-flash-preview")

        msg = UserMessage(
            text="Transcribe every piece of text visible in this building plan image.",
            file_contents=[ImageContent(image_base64=png_b64)],
        )
        resp = await chat.send_message(msg)
        if isinstance(resp, str):
            return resp
        return getattr(resp, "text", None) or str(resp)
    except Exception as exc:  # pragma: no cover - optional path
        print(f"[plan_reader.ocr] AI OCR fallback failed, continuing without it: {exc}")
        return None
