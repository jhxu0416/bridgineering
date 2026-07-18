"""FastAPI app: serves the single-page frontend and the two API endpoints.

One process serves both the static HTML and the API (see CLAUDE.md).

    POST /api/decompose  -> LLM decompose tool -> {listen_for, ehr_condition, action}
    POST /api/grill      -> prevalence + severity + LLM grill -> {corner_cases: [...]}

All arithmetic is done in prevalence.py; the LLM only selects/frames cases.
"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import grilling

load_dotenv()

APP_DIR = Path(__file__).parent
INDEX_HTML = APP_DIR / "static" / "index.html"

app = FastAPI(title="Clinical Rule Authoring — grilling flow")


# ---- request models -------------------------------------------------------

class DecomposeRequest(BaseModel):
    rule: str


class GrillRequest(BaseModel):
    rule: str
    listen_for: str
    ehr_condition: str
    action: str


# ---- routes ---------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(INDEX_HTML)


@app.get("/favicon.ico")
def favicon():
    # No favicon file — return 204 so the browser's auto-request doesn't 404.
    return Response(status_code=204)


@app.post("/api/decompose")
def decompose(req: DecomposeRequest):
    if not req.rule.strip():
        raise HTTPException(status_code=400, detail="Rule text is empty.")
    try:
        return grilling.decompose(req.rule)
    except Exception as e:  # surface a clean error to the frontend, not a 500 stack
        raise HTTPException(status_code=502, detail=f"Decompose failed: {e}")


@app.post("/api/grill")
def grill(req: GrillRequest):
    decomposition = {
        "listen_for": req.listen_for,
        "ehr_condition": req.ehr_condition,
        "action": req.action,
    }
    try:
        corner_cases = grilling.grill_rule(req.rule, decomposition)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Grill failed: {e}")
    return {"corner_cases": corner_cases}
