"""FastAPI application — JSON API + dashboard for Haven.

Serves:
  - /api/* — JSON endpoints for the pipeline, inventory, actions, and evidence
  - /       — dashboard (the demo's money shot)

Public-demo safeguards:
  - Synthetic demo family only (``ScanRequest`` forbids arbitrary payloads).
  - Explicit user consent is required before ``POST /api/scan`` dispatches any
    external request.
  - Sliding-window rate limit on ``POST /api/scan`` (``HAVEN_SCAN_RATE_LIMIT``
    scans per hour, default 10) protects provider spend.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env *before* importing the haven modules: llm.py and research.py read
# their configuration (endpoint, model overrides, provider mode) from the
# environment, so values added to .env must be visible at import time.
load_dotenv()

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict

from haven import llm
from haven.evidence import evidence_status, read_egress_log, summarize_egress
from haven.models import PipelineState
from haven.offline import provider_mode
from haven.pipeline import (
    approve_action,
    mark_confirmed,
    mark_sent,
    run_pipeline,
)
from haven.seed import generate_family, redact_high_sensitivity

app = FastAPI(
    title="Haven",
    description="Privacy-first family data-exposure agent — local matching, identifier-free research, human-gated drafts.",
    version="0.1.0",
)

# ── Templates & static files ──────────────────────────────────────────
WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))

if (WEB_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

# ── In-memory state (sufficient for a hackathon demo) ─────────────────
_state: PipelineState | None = None

# ── Sliding-window scan rate limiter ──────────────────────────────────
_WINDOW_SECONDS = 3600.0
_rate_lock = threading.Lock()
_scan_timestamps: deque[float] = deque()


def _scan_limit() -> int:
    raw = os.environ.get("HAVEN_SCAN_RATE_LIMIT", "10").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 10


def _check_rate_limit() -> None:
    limit = _scan_limit()
    now = time.monotonic()
    with _rate_lock:
        while _scan_timestamps and now - _scan_timestamps[0] >= _WINDOW_SECONDS:
            _scan_timestamps.popleft()
        if len(_scan_timestamps) >= limit:
            retry_after = max(1, int(_WINDOW_SECONDS - (now - _scan_timestamps[0])))
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Public demo scan rate limit exceeded ({limit} scans/hour). "
                    f"Try again in {retry_after}s."
                ),
                headers={"Retry-After": str(retry_after)},
            )
        _scan_timestamps.append(now)


def reset_rate_limit() -> None:
    """Clear rate-limit history (used by tests)."""
    with _rate_lock:
        _scan_timestamps.clear()


def _get_state() -> PipelineState:
    global _state
    if _state is None:
        family = generate_family()
        _state = PipelineState(family=family, provider_mode=provider_mode())
    return _state


def _set_state(state: PipelineState) -> None:
    global _state
    _state = state


class ScanRequest(BaseModel):
    """Explicit consent payload for starting a scan (synthetic demo only)."""

    model_config = ConfigDict(extra="forbid")
    consent: bool = False


# ── Dashboard ─────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard — the demo's money shot."""
    state = _get_state()
    egress = read_egress_log()
    egress_summary = summarize_egress(egress)
    ev_status = evidence_status(egress)
    tier_usage = llm.get_usage_log()

    n_verified = sum(1 for e in state.exposures if e.match_status == "verified")
    n_candidate = sum(1 for e in state.exposures if e.match_status == "candidate")
    n_rejected = sum(1 for e in state.exposures if e.match_status == "rejected")
    n_exposures = len(state.exposures)
    n_sent = sum(1 for a in state.actions if a.status in ("sent", "confirmed_removed"))
    n_confirmed = sum(1 for a in state.actions if a.status == "confirmed_removed")
    n_pending = sum(
        1 for a in state.actions if a.status in ("drafted", "approved", "pending")
    )

    tf_host = (
        llm.base_url().split("://", 1)[-1].split("/", 1)[0]
        or "api.tokenfactory.us-central1.nebius.com"
    )
    mode = state.provider_mode if state.actions or state.inventory else provider_mode()

    return TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {
            "state": state,
            "n_exposures": n_exposures,
            "n_verified": n_verified,
            "n_candidate": n_candidate,
            "n_rejected": n_rejected,
            "n_sent": n_sent,
            "n_confirmed": n_confirmed,
            "n_pending": n_pending,
            "egress_summary": egress_summary,
            "egress_records": egress,
            "evidence_status": ev_status,
            "tier_usage": tier_usage,
            "provider_mode": mode,
            "token_factory_host": tf_host,
            "scan_rate_limit": _scan_limit(),
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
async def start_scan(payload: ScanRequest | None = Body(default=None)):
    """Run the discovery -> local match -> procedure -> draft pipeline.

    Requires explicit user consent (``{"consent": true}``) and enforces a
    sliding-window rate limit to protect provider spend. Only runs against
    the built-in deterministic synthetic family.
    """
    if payload is None or not payload.consent:
        raise HTTPException(
            status_code=400,
            detail=(
                "Explicit user consent is required before sending identifier-free "
                "queries to external providers. Pass {\"consent\": true}."
            ),
        )

    _check_rate_limit()

    state = _get_state()
    try:
        new_state = run_pipeline(state.family)
        _set_state(new_state)
        return {
            "status": "complete",
            "provider_mode": new_state.provider_mode,
            "inventory_count": len(new_state.inventory),
            "exposures_found": len(new_state.exposures),
            "verified_matches": sum(
                1 for e in new_state.exposures if e.match_status == "verified"
            ),
            "candidate_matches": sum(
                1 for e in new_state.exposures if e.match_status == "candidate"
            ),
            "procedures_extracted": len(new_state.procedures),
            "drafts_created": len(new_state.actions),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/inventory")
async def get_inventory():
    """Return discovered data brokers and their coverage mode (local_fixture vs manual_only)."""
    return _get_state().inventory


@app.get("/api/exposures")
async def get_exposures():
    """Return all locally matched exposures (verified, candidate, rejected)."""
    return _get_state().exposures


@app.get("/api/actions")
async def get_actions():
    """Return all removal actions with their current status."""
    return _get_state().actions


@app.get("/api/strategy")
async def get_strategy():
    """Return the Ultra-tier multi-site removal strategy, if generated."""
    return {"strategy": _get_state().strategy}


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
    values. The dashboard labels whether logs are real, simulated, or
    unavailable, and never claims request-body privacy from network metadata.
    """
    records = read_egress_log()
    return {
        "source": "enforcement_layer",
        "evidence_status": evidence_status(records),
        "note": "Data from OpenShell OCSF audit logs — not agent-reported (destinations and decisions only, not payload contents)",
        "summary": summarize_egress(records),
        "records": records,
    }


@app.get("/api/tier-usage")
async def get_tier_usage():
    """Return per-tier token and latency usage for the dashboard chart."""
    usage = llm.get_usage_log()

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
                "simulated": u.simulated,
            }
        entry = by_tier[u.tier]
        entry["total_input_tokens"] += u.input_tokens
        entry["total_output_tokens"] += u.output_tokens
        entry["call_count"] += 1
        entry["total_latency_ms"] += u.latency_ms
        entry["simulated"] = entry["simulated"] or u.simulated

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
        "provider_mode": provider_mode(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
