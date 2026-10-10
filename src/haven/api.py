"""FastAPI application — JSON API + dashboard for Haven.

Serves:
  - /api/* — JSON endpoints for the pipeline, actions, and evidence
  - /       — dashboard (the demo's money shot)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env *before* importing the haven modules: llm.py and research.py read
# their configuration (endpoint, model overrides) from the environment, so a
# key added to .env must be visible to them at import time.
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from haven import llm
from haven.evidence import read_egress_log, summarize_egress
from haven.models import PipelineState
from haven.pipeline import (
    approve_action,
    mark_confirmed,
    mark_sent,
    run_pipeline,
)
from haven.seed import generate_family, redact_high_sensitivity

app = FastAPI(
    title="Haven",
    description="Family data-exposure agent — finds and removes personal data from the public web.",
    version="0.1.0",
)

# ── Templates & static files ──────────────────────────────────────────
WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))

if (WEB_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

# ── In-memory state (sufficient for a hackathon demo) ─────────────────
_state: PipelineState | None = None


def _get_state() -> PipelineState:
    global _state
    if _state is None:
        family = generate_family()
        _state = PipelineState(family=family)
    return _state


def _set_state(state: PipelineState) -> None:
    global _state
    _state = state


# ── Dashboard ─────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard — the demo's money shot."""
    state = _get_state()
    egress = read_egress_log()
    egress_summary = summarize_egress(egress)
    tier_usage = llm.get_usage_log()

    # Compute summary counts
    n_exposures = len(state.exposures)
    n_sent = sum(1 for a in state.actions if a.status in ("sent", "confirmed_removed"))
    n_confirmed = sum(1 for a in state.actions if a.status == "confirmed_removed")
    n_pending = sum(1 for a in state.actions if a.status in ("drafted", "approved", "pending"))

    return TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {
            "state": state,
            "n_exposures": n_exposures,
            "n_sent": n_sent,
            "n_confirmed": n_confirmed,
            "n_pending": n_pending,
            "egress_summary": egress_summary,
            "egress_records": egress,
            "tier_usage": tier_usage,
        },
    )


# ── API endpoints ─────────────────────────────────────────────────────


@app.get("/api/family")
async def get_family(reveal: bool = False):
    """Return the current synthetic family.

    High-sensitivity identifier values are redacted by default so the API
    agrees with the dashboard template that consumes the same data. Pass
    ``?reveal=true`` for the raw values, which is a local-operator escape
    hatch: the hosted demo URL is public, and the dashboard labels this
    distinction on screen.
    """
    family = _get_state().family
    return family if reveal else redact_high_sensitivity(family)


@app.post("/api/scan")
async def start_scan():
    """Run the full discovery pipeline.

    This is the primary action: search for the family's data exposure,
    extract opt-out procedures, and draft removal requests.
    """
    state = _get_state()
    try:
        new_state = run_pipeline(state.family)
        _set_state(new_state)
        return {
            "status": "complete",
            "exposures_found": len(new_state.exposures),
            "procedures_extracted": len(new_state.procedures),
            "drafts_created": len(new_state.actions),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/exposures")
async def get_exposures():
    """Return all discovered exposures."""
    return _get_state().exposures


@app.get("/api/actions")
async def get_actions():
    """Return all removal actions with their current status."""
    return _get_state().actions


@app.post("/api/actions/{action_id}/approve")
async def approve(action_id: str):
    """Approve a drafted removal request for sending (human-in-the-loop)."""
    state = _get_state()
    for action in state.actions:
        if action.id == action_id:
            try:
                approve_action(action)
                return {"status": action.status, "id": action.id}
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=404, detail=f"Action {action_id} not found")


@app.post("/api/actions/{action_id}/sent")
async def mark_action_sent(action_id: str):
    """Mark an approved action as sent (human confirmed they sent it)."""
    state = _get_state()
    for action in state.actions:
        if action.id == action_id:
            try:
                mark_sent(action)
                return {"status": action.status, "id": action.id}
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=404, detail=f"Action {action_id} not found")


@app.post("/api/actions/{action_id}/confirm")
async def confirm_removal(action_id: str):
    """Mark a sent action as confirmed removed."""
    state = _get_state()
    for action in state.actions:
        if action.id == action_id:
            try:
                mark_confirmed(action)
                return {"status": action.status, "id": action.id}
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=404, detail=f"Action {action_id} not found")


@app.get("/api/evidence")
async def get_evidence():
    """Return egress evidence from the enforcement layer.

    This data comes from OpenShell audit logs, NOT from agent-reported
    values.  The dashboard labels this distinction on-screen.
    """
    records = read_egress_log()
    return {
        "source": "enforcement_layer",
        "note": "Data from OpenShell OCSF audit logs — not agent-reported",
        "summary": summarize_egress(records),
        "records": records,
    }


@app.get("/api/tier-usage")
async def get_tier_usage():
    """Return per-tier token and latency usage for the dashboard chart."""
    usage = llm.get_usage_log()

    # Aggregate by tier
    by_tier: dict[str, dict] = {}
    for u in usage:
        if u.tier not in by_tier:
            by_tier[u.tier] = {
                "tier": u.tier,
                "model": u.model,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "call_count": 0,
                "avg_latency_ms": 0,
                "total_latency_ms": 0,
            }
        entry = by_tier[u.tier]
        entry["total_input_tokens"] += u.input_tokens
        entry["total_output_tokens"] += u.output_tokens
        entry["call_count"] += 1
        entry["total_latency_ms"] += u.latency_ms

    for entry in by_tier.values():
        if entry["call_count"] > 0:
            entry["avg_latency_ms"] = round(
                entry["total_latency_ms"] / entry["call_count"], 1
            )

    return {
        "by_tier": list(by_tier.values()),
        "raw": [u.model_dump() for u in usage],
    }


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
