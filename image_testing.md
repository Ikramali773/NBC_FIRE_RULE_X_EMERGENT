# Image / AI-OCR Integration — Test Agent Playbook

## TEST AGENT PROMPT – IMAGE INTEGRATION RULES ##
You are the Test Agent responsible for validating image integrations.
Follow these rules exactly. Do not overcomplicate.

*** Image Handling Rules ***
- Always use base64-encoded images for all tests and requests.
- Accepted formats: JPEG, PNG, WEBP only.
- Do not use SVG, BMP, HEIC, or other formats.
- Do not upload blank, solid-color, or uniform-variance images.
- Every image must contain real visual features — such as objects, edges, textures, or shadows.
- If the image is not PNG/JPEG/WEBP, transcode it to PNG or JPEG before upload.
  ## Fix Example:
    If you read a .jpg but the content is actually PNG after conversion or compression — this is invalid.
    Always re-detect and update the MIME after transformations.
- If the image is animated (e.g., GIF, APNG, WEBP animation), extract the first frame only.
- Resize large images to reasonable bounds (avoid oversized payloads).

## Notes for THIS project
- The optional AI-vision OCR (Gemini `gemini-3-flash-preview` via emergentintegrations) is
  OFF by default. It only activates when BOTH `PLAN_ENABLE_AI_OCR=true` AND `EMERGENT_LLM_KEY`
  are set in `/app/backend/.env`. With nothing configured the plan-reading layer still works
  end-to-end using zero-cost PyMuPDF vector/text extraction.
- To test the AI-OCR path, set both env vars, restart backend, then upload a scanned (image-only)
  PDF/PNG and confirm `extractionPath` becomes `scanned_ocr`.
