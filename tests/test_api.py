"""The FastAPI surface: JSON endpoints, the dashboard, and the human gates."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from haven import api, llm
from haven.models import PipelineState, TierUsage

from conftest import make_action, make_exposure, make_procedure


def _state_with_one_action(family):
    exposure = make_exposure()
    procedure = make_procedure(exposure)
    action = make_action(exposure, procedure)
    return PipelineState(
        family=family,
        exposures=[exposure],
        procedures=[procedure],
        actions=[action],
    )


# ── Read endpoints ─────────────────────────────────────────────────────


def test_health(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert "timestamp" in body


def test_family_endpoint_returns_the_synthetic_family(client):
    body = client.get("/api/family").json()

    assert len(body["members"]) == 4
    assert body["city"] == "Springfield"


def test_exposures_and_actions_start_empty(client):
    assert client.get("/api/exposures").json() == []
    assert client.get("/api/actions").json() == []


def test_dashboard_renders_with_no_data(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Haven" in response.text


def test_dashboard_renders_exposures_and_actions(client, family):
    api._set_state(_state_with_one_action(family))

    html = client.get("/").text

    assert "Spokeo" in html
    assert "act00001" in html
    assert "drafted" in html


def test_dashboard_labels_the_evidence_source(client):
    """The panel must not look like agent-reported data."""
    html = client.get("/").text

    assert "enforcement" in html.lower()


# ── Scan ───────────────────────────────────────────────────────────────


def test_scan_reports_pipeline_counts(client, family, monkeypatch):
    monkeypatch.setattr(
        "haven.api.run_pipeline", lambda fam, **kwargs: _state_with_one_action(fam)
    )

    response = client.post("/api/scan")

    assert response.status_code == 200
    assert response.json() == {
        "status": "complete",
        "exposures_found": 1,
        "procedures_extracted": 1,
        "drafts_created": 1,
    }
    assert len(client.get("/api/exposures").json()) == 1


def test_scan_failure_surfaces_as_500(client, monkeypatch):
    def boom(fam, **kwargs):
        raise RuntimeError("NEBIUS_API_KEY environment variable is not set.")

    monkeypatch.setattr("haven.api.run_pipeline", boom)

    response = client.post("/api/scan")

    assert response.status_code == 500
    assert "NEBIUS_API_KEY" in response.json()["detail"]


def test_scan_keeps_previous_state_on_failure(client, family, monkeypatch):
    api._set_state(_state_with_one_action(family))
    monkeypatch.setattr(
        "haven.api.run_pipeline",
        lambda fam, **kwargs: (_ for _ in ()).throw(RuntimeError("upstream 500")),
    )

    assert client.post("/api/scan").status_code == 500
    assert len(client.get("/api/exposures").json()) == 1


# ── Human gates ────────────────────────────────────────────────────────


def test_approve_sent_confirm_flow(client, family):
    api._set_state(_state_with_one_action(family))

    approved = client.post("/api/actions/act00001/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    sent = client.post("/api/actions/act00001/sent")
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"

    confirmed = client.post("/api/actions/act00001/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed_removed"

    assert client.get("/api/actions").json()[0]["status"] == "confirmed_removed"


def test_marking_sent_without_approval_is_refused(client, family):
    api._set_state(_state_with_one_action(family))

    response = client.post("/api/actions/act00001/sent")

    assert response.status_code == 400
    assert "approved" in response.json()["detail"]


def test_confirming_before_sending_is_refused(client, family):
    api._set_state(_state_with_one_action(family))
    client.post("/api/actions/act00001/approve")

    response = client.post("/api/actions/act00001/confirm")

    assert response.status_code == 400
    assert "sent" in response.json()["detail"]


def test_double_approval_is_refused(client, family):
    api._set_state(_state_with_one_action(family))
    client.post("/api/actions/act00001/approve")

    response = client.post("/api/actions/act00001/approve")

    assert response.status_code == 400
    assert "Cannot approve" in response.json()["detail"]


@pytest.mark.parametrize("verb", ["approve", "sent", "confirm"])
def test_unknown_action_id_returns_404(client, verb: str):
    response = client.post(f"/api/actions/nope/{verb}")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


# ── Evidence ───────────────────────────────────────────────────────────


def test_evidence_endpoint_is_empty_without_a_log(client, monkeypatch):
    monkeypatch.setattr("haven.evidence.AUDIT_LOG_PATH", "does-not-exist.jsonl")

    body = client.get("/api/evidence").json()

    assert body["source"] == "enforcement_layer"
    assert "not agent-reported" in body["note"]
    assert body["summary"] == {"total_allowed": 0, "total_denied": 0, "destinations": []}
    assert body["records"] == []


def test_evidence_endpoint_reads_the_audit_log(client, tmp_path, monkeypatch):
    log = tmp_path / "egress.jsonl"
    log.write_text(
        "\n".join(
            [
                json.dumps({"destination_host": "api.tavily.com", "request_count": 2}),
                json.dumps(
                    {
                        "destination_host": "collector.example",
                        "decision": "denied",
                        "matched_policy": "deny-collectors",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("haven.evidence.AUDIT_LOG_PATH", str(log))

    body = client.get("/api/evidence").json()

    assert body["summary"]["total_allowed"] == 2
    assert body["summary"]["total_denied"] == 1
    assert len(body["records"]) == 2


# ── Tier usage ─────────────────────────────────────────────────────────


def test_tier_usage_is_empty_before_any_call(client):
    body = client.get("/api/tier-usage").json()

    assert body == {"by_tier": [], "raw": []}


def test_tier_usage_aggregates_by_tier(client):
    now = datetime.now(timezone.utc)
    llm._usage_log.extend(
        [
            TierUsage(
                model=llm.TIER_MODELS["nano"],
                tier="nano",
                input_tokens=100,
                output_tokens=20,
                latency_ms=10.0,
                purpose="classify_search_result",
                timestamp=now,
            ),
            TierUsage(
                model=llm.TIER_MODELS["nano"],
                tier="nano",
                input_tokens=300,
                output_tokens=40,
                latency_ms=20.0,
                purpose="classify_search_result",
                timestamp=now,
            ),
            TierUsage(
                model=llm.TIER_MODELS["super"],
                tier="super",
                input_tokens=1000,
                output_tokens=500,
                latency_ms=900.0,
                purpose="extract_optout_procedure",
                timestamp=now,
            ),
        ]
    )

    body = client.get("/api/tier-usage").json()

    by_tier = {entry["tier"]: entry for entry in body["by_tier"]}
    assert set(by_tier) == {"nano", "super"}
    assert by_tier["nano"]["call_count"] == 2
    assert by_tier["nano"]["total_input_tokens"] == 400
    assert by_tier["nano"]["total_output_tokens"] == 60
    assert by_tier["nano"]["avg_latency_ms"] == pytest.approx(15.0)
    assert by_tier["super"]["avg_latency_ms"] == pytest.approx(900.0)
    assert len(body["raw"]) == 3
