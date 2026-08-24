# Test Credentials

This application has **no authentication** — there are no user accounts, logins, or
API keys required to use it.

- Frontend: port 3000 · Backend: port 8001 · External URL:
  https://layout-mapper-5.preview.emergentagent.com
- Optional AI-vision OCR is OFF by default. To enable, set in `/app/backend/.env`:
  `PLAN_ENABLE_AI_OCR=true` and `EMERGENT_LLM_KEY=<key>`, then restart backend.
- Test fixture for the plan layer: `/app/backend/tests/_synthetic_plan.pdf`
  (regenerate via `/root/.venv/bin/python /app/backend/tests/make_synthetic_plan.py`).
