"""The egress-evidence reader.

The dashboard claims this data comes from the enforcement layer rather than
from the agent, so the parser has to cope with real OCSF entries, tolerate
truncated log lines, and never invent an 'allowed' it did not read.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from haven import evidence
from haven.models import EgressRecord


def _record(**overrides) -> EgressRecord:
    body = {
        "timestamp": datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc),
        "destination_host": "api.tokenfactory.nebius.com",
        "decision": "allowed",
        "matched_policy": "allow-nebius",
        "bytes_out": 512,
        "request_count": 1,
    }
    body.update(overrides)
    return EgressRecord(**body)


# ── OCSF parsing ───────────────────────────────────────────────────────


def test_parses_a_full_ocsf_record():
    record = evidence._parse_ocsf_record(
        {
            "time": 1714564800,
            "dst_endpoint": {"hostname": "api.tokenfactory.nebius.com", "ip": "1.2.3.4"},
            "disposition_id": 1,
            "policy": {"name": "allow-nebius"},
            "traffic": {"bytes_out": 4096},
            "request_count": 3,
        }
    )

    assert record.destination_host == "api.tokenfactory.nebius.com"
    assert record.decision == "allowed"
    assert record.matched_policy == "allow-nebius"
    assert record.bytes_out == 4096
    assert record.request_count == 3
    assert record.timestamp == datetime.fromtimestamp(1714564800, tz=timezone.utc)


def test_disposition_id_two_is_denied():
    record = evidence._parse_ocsf_record({"disposition_id": 2})

    assert record.decision == "denied"


def test_any_non_allow_disposition_is_treated_as_denied():
    record = evidence._parse_ocsf_record({"disposition_id": 7})

    assert record.decision == "denied"


def test_denied_defaults_to_the_ip_when_no_hostname():
    record = evidence._parse_ocsf_record(
        {"dst_endpoint": {"ip": "203.0.113.9"}, "disposition_id": 2}
    )

    assert record.destination_host == "203.0.113.9"


def test_unknown_destination_is_labelled_not_blank():
    record = evidence._parse_ocsf_record({})

    assert record.destination_host == "unknown"


def test_simplified_flat_record_is_supported():
    record = evidence._parse_ocsf_record(
        {
            "timestamp": "2024-05-01T12:00:00+00:00",
            "destination_host": "tracker.example",
            "decision": "denied",
            "matched_policy": "deny-all",
            "bytes_out": 10,
        }
    )

    assert record.destination_host == "tracker.example"
    assert record.decision == "denied"
    assert record.matched_policy == "deny-all"
    assert record.bytes_out == 10
    assert record.request_count is None  # omitted when not in source event
    assert record.timestamp == datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)


def test_missing_timestamp_falls_back_to_now():
    before = datetime.now(timezone.utc)
    record = evidence._parse_ocsf_record({"destination_host": "x"})
    after = datetime.now(timezone.utc)

    assert before <= record.timestamp <= after


def test_missing_byte_count_is_none():
    record = evidence._parse_ocsf_record({"destination_host": "x"})

    assert record.bytes_out is None
    assert record.request_count is None


def test_matched_policy_is_optional():
    record = evidence._parse_ocsf_record({"destination_host": "x", "disposition_id": 1})

    assert record.matched_policy is None


# ── Log reading ────────────────────────────────────────────────────────


def test_missing_log_file_yields_no_records(tmp_path: Path):
    assert evidence.read_egress_log(str(tmp_path / "absent.jsonl")) == []


def test_reads_jsonl_records(tmp_path: Path):
    log = tmp_path / "egress.jsonl"
    log.write_text(
        "\n".join(
            [
                json.dumps({"destination_host": "a.example", "decision": "allowed"}),
                json.dumps({"destination_host": "b.example", "disposition_id": 2}),
            ]
        ),
        encoding="utf-8",
    )

    records = evidence.read_egress_log(str(log))

    assert [r.destination_host for r in records] == ["a.example", "b.example"]
    assert [r.decision for r in records] == ["allowed", "denied"]


def test_blank_lines_are_ignored(tmp_path: Path):
    log = tmp_path / "egress.jsonl"
    log.write_text(
        '\n{"destination_host": "a.example"}\n\n   \n', encoding="utf-8"
    )

    assert len(evidence.read_egress_log(str(log))) == 1


def test_truncated_lines_are_skipped_without_losing_good_ones(tmp_path: Path):
    """A log cut off mid-write must not make the whole evidence panel disappear."""
    log = tmp_path / "egress.jsonl"
    log.write_text(
        '\n'.join(
            [
                '{"destination_host": "good.example"}',
                '{"destination_host": "trunc',
                '{"destination_host": "also-good.example"}',
            ]
        ),
        encoding="utf-8",
    )

    records = evidence.read_egress_log(str(log))

    assert [r.destination_host for r in records] == ["good.example", "also-good.example"]


def test_records_with_an_unrecognised_decision_are_skipped(tmp_path: Path):
    log = tmp_path / "egress.jsonl"
    log.write_text(
        "\n".join(
            [
                '{"destination_host": "good.example", "decision": "allowed"}',
                '{"destination_host": "weird.example", "decision": "quarantined"}',
            ]
        ),
        encoding="utf-8",
    )

    records = evidence.read_egress_log(str(log))

    assert [r.destination_host for r in records] == ["good.example"]


def test_default_path_points_at_the_openshell_audit_log():
    """Supervisors write /var/log/openshell-ocsf.YYYY-MM-DD.log with rotation."""
    assert "openshell-ocsf" in evidence.AUDIT_LOG_PATH
    assert evidence.AUDIT_LOG_PATH.endswith(".log")


def test_write_simulated_log_round_trips(tmp_path: Path):
    log = tmp_path / "nested" / "sim.jsonl"
    original = [
        _record(destination_host="api.tokenfactory.nebius.com", request_count=4),
        _record(destination_host="api.tavily.com", decision="denied", matched_policy="deny"),
    ]

    evidence.write_simulated_log(original, str(log))
    restored = evidence.read_egress_log(str(log))

    assert [r.destination_host for r in restored] == [
        "api.tokenfactory.nebius.com",
        "api.tavily.com",
    ]
    assert restored[0].request_count == 4
    assert restored[1].decision == "denied"
    assert restored[1].matched_policy == "deny"


# ── Summaries ──────────────────────────────────────────────────────────


def test_summary_of_no_records_is_empty_but_well_formed():
    summary = evidence.summarize_egress([])

    assert summary == {"total_allowed": 0, "total_denied": 0, "destinations": []}


def test_summary_counts_requests_not_lines():
    summary = evidence.summarize_egress(
        [
            _record(destination_host="a.example", request_count=3),
            _record(destination_host="a.example", request_count=2),
        ]
    )

    assert summary["total_allowed"] == 5
    assert summary["destinations"][0]["allowed"] == 5
    assert summary["destinations"][0]["host"] == "a.example"


def test_summary_splits_allowed_and_denied_per_host():
    summary = evidence.summarize_egress(
        [
            _record(destination_host="a.example", request_count=2),
            _record(destination_host="a.example", decision="denied", request_count=1),
            _record(destination_host="b.example", decision="denied", request_count=4),
        ]
    )

    assert summary["total_allowed"] == 2
    assert summary["total_denied"] == 5

    by_host = {d["host"]: d for d in summary["destinations"]}
    assert by_host["a.example"]["allowed"] == 2
    assert by_host["a.example"]["denied"] == 1
    assert by_host["b.example"]["denied"] == 4


def test_summary_accumulates_bytes_and_sorts_policies():
    summary = evidence.summarize_egress(
        [
            _record(destination_host="a.example", bytes_out=100, matched_policy="z-policy"),
            _record(destination_host="a.example", bytes_out=50, matched_policy="a-policy"),
        ]
    )

    destination = summary["destinations"][0]
    assert destination["bytes_out"] == 150
    assert destination["policies"] == ["a-policy", "z-policy"]


def test_summary_destinations_are_sorted_by_host():
    summary = evidence.summarize_egress(
        [
            _record(destination_host="z.example"),
            _record(destination_host="a.example"),
            _record(destination_host="m.example"),
        ]
    )

    assert [d["host"] for d in summary["destinations"]] == [
        "a.example",
        "m.example",
        "z.example",
    ]


def test_summary_is_json_serialisable():
    """The dashboard renders this through the API, so no sets may leak out."""
    summary = evidence.summarize_egress([_record(matched_policy="p")])

    json.dumps(summary)


# ── Real OpenShell OCSF v1.8.0 records ─────────────────────────────────
# Field shapes copied from NVIDIA's published OCSF JSON export examples for
# OpenShell. These are the shapes the dashboard's evidence panel will actually
# receive, so they are asserted rather than the older invented ones.


def _ocsf_allowed() -> dict[str, object]:
    return {
        "class_uid": 4001,
        "class_name": "Network Activity",
        "category_uid": 4,
        "activity_id": 1,
        "severity_id": 1,
        "status_id": 1,
        "time": 1775014138811,
        "message": "CONNECT allowed api.github.com:443",
        "metadata": {
            "product": {"name": "OpenShell Sandbox Supervisor", "vendor_name": "NVIDIA"}
        },
        "action_id": 1,
        "action": "Allowed",
        "disposition_id": 1,
        "disposition": "Allowed",
        "dst_endpoint": {"domain": "api.github.com", "port": 443},
        "src_endpoint": {"ip": "10.42.0.31", "port": 37494},
        "actor": {"process": {"name": "/usr/bin/curl", "pid": 57}},
        "firewall_rule": {"name": "github_api", "type": "opa"},
    }


def _ocsf_denied() -> dict[str, object]:
    return {
        "class_uid": 4001,
        "class_name": "Network Activity",
        "activity_id": 1,
        "severity_id": 3,
        "status_id": 2,
        "time": 1775014139000,
        "action_id": 2,
        "action": "Denied",
        "disposition_id": 2,
        "disposition": "Blocked",
        "status_detail": "no matching policy",
        "message": "CONNECT denied httpbin.org:443",
        "dst_endpoint": {"domain": "httpbin.org", "port": 443},
        "actor": {"process": {"name": "/usr/bin/curl", "pid": 63}},
        "firewall_rule": {"name": "-", "type": "opa"},
    }


def test_ocsf_time_is_epoch_milliseconds():
    """OCSF `time` is milliseconds. Reading it as seconds lands in year 58246."""
    record = evidence._parse_ocsf_record(_ocsf_allowed())

    assert record.timestamp == datetime.fromtimestamp(
        1775014138811 / 1000, tz=timezone.utc
    )
    assert record.timestamp.year == 2026


def test_ocsf_destination_comes_from_dst_endpoint_domain():
    record = evidence._parse_ocsf_record(_ocsf_allowed())

    assert record.destination_host == "api.github.com"


def test_ocsf_matched_policy_comes_from_firewall_rule_name():
    record = evidence._parse_ocsf_record(_ocsf_allowed())

    assert record.matched_policy == "github_api"


def test_ocsf_denied_record_has_no_matched_policy():
    """OpenShell writes firewall_rule.name '-' when no rule matched."""
    record = evidence._parse_ocsf_record(_ocsf_denied())

    assert record.decision == "denied"
    assert record.matched_policy is None


def test_ocsf_http_activity_is_included():
    record = dict(_ocsf_allowed(), class_uid=4002, class_name="HTTP Activity")

    parsed = evidence._parse_ocsf_record(record)

    assert parsed.destination_host == "api.github.com"


def test_non_network_event_classes_are_rejected():
    """Process and config events carry no destination and must not become rows."""
    record = dict(_ocsf_allowed(), class_uid=1007, class_name="Process Activity")

    with pytest.raises(ValueError, match="not a network event"):
        evidence._parse_ocsf_record(record)


def test_non_network_records_are_skipped_by_the_reader(tmp_path: Path):
    log = tmp_path / "openshell-ocsf.2026-05-01.log"
    log.write_text(
        "\n".join(
            [
                json.dumps(_ocsf_allowed()),
                json.dumps(dict(_ocsf_allowed(), class_uid=1007)),
                json.dumps(_ocsf_denied()),
            ]
        ),
        encoding="utf-8",
    )

    records = evidence.read_egress_log(str(log))

    assert [r.destination_host for r in records] == ["api.github.com", "httpbin.org"]


def test_stderr_prefixed_json_records_are_parsed(tmp_path: Path):
    """`docker logs` emits '<timestamp> OCSF-JSON {...}' rather than bare JSON."""
    log = tmp_path / "docker-logs.txt"
    log.write_text(
        "2026-10-07T23:21:19.000Z OCSF-JSON " + json.dumps(_ocsf_denied()) + "\n",
        encoding="utf-8",
    )

    records = evidence.read_egress_log(str(log))

    assert len(records) == 1
    assert records[0].destination_host == "httpbin.org"


def test_rotating_log_glob_reads_the_newest_file(tmp_path: Path):
    older = tmp_path / "openshell-ocsf.2026-05-01.log"
    newer = tmp_path / "openshell-ocsf.2026-05-02.log"
    older.write_text(json.dumps(dict(_ocsf_allowed(), dst_endpoint={"domain": "old.example"})), encoding="utf-8")
    newer.write_text(json.dumps(dict(_ocsf_allowed(), dst_endpoint={"domain": "new.example"})), encoding="utf-8")

    records = evidence.read_egress_log(str(tmp_path / "openshell-ocsf*.log"))

    assert [r.destination_host for r in records] == ["new.example"]


def test_glob_with_no_matches_yields_no_records(tmp_path: Path):
    assert evidence.read_egress_log(str(tmp_path / "openshell-ocsf*.log")) == []


def test_ocsf_record_without_traffic_leaves_bytes_and_request_count_none():
    """OpenShell's published exemplars omit byte counts; never invent 0 or 1."""
    record = evidence._parse_ocsf_record(_ocsf_allowed())

    assert record.bytes_out is None
    assert record.request_count is None


def test_disposition_zero_falls_back_to_the_action_string():
    record = dict(_ocsf_allowed(), disposition_id=0, action="Denied")

    assert evidence._parse_ocsf_record(record).decision == "denied"


def test_evidence_status_distinguishes_real_simulated_and_unavailable(tmp_path: Path):
    assert evidence.evidence_status([]) == "unavailable"

    sim_log = tmp_path / "sim.jsonl"
    evidence.write_simulated_log([_record()], str(sim_log))
    sim_records = evidence.read_egress_log(str(sim_log))
    assert all(r.simulated for r in sim_records)
    assert evidence.evidence_status(sim_records) == "simulated"

    real_record = evidence._parse_ocsf_record(_ocsf_allowed())
    assert real_record.simulated is False
    assert evidence.evidence_status([real_record]) == "real"
