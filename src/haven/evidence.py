"""Host-side reader for OpenShell audit / OCSF egress logs.

The dashboard's "what left the machine" panel reads from these logs so that
the agent cannot lie about its network activity. The data originates in the
enforcement layer, never in the agent.

Field shapes here are taken from NVIDIA's published OCSF JSON export for
OpenShell (OCSF v1.8.0, class_uid 4001 Network Activity / 4002 HTTP Activity).
Three details matter and are easy to get wrong:

* OCSF ``time`` is epoch **milliseconds**, not seconds.
* The destination host is ``dst_endpoint.domain`` (``hostname``/``ip`` are
  fallbacks), not ``dst_endpoint.hostname``.
* The matched policy is ``firewall_rule.name``, and OpenShell writes ``"-"``
  when no rule matched.

The simplified flat format is still accepted so that tests and a local
simulated log keep working without a sandbox.
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from haven.models import EgressRecord

# Where OpenShell writes OCSF JSONL. Supervisors write
# ``/var/log/openshell-ocsf.YYYY-MM-DD.log`` with three-file retention; the
# gateway's own sink is configured in gateway.toml. Note that
# ``openshell sandbox exec`` cannot read the supervisor's copy -- collect it
# from the host (``docker logs``/``kubectl logs``) or a host-side mount.
# Accepts a glob so a rotating filename works.
AUDIT_LOG_PATH = os.environ.get(
    "HAVEN_AUDIT_LOG", "/var/log/openshell-ocsf*.log"
)

# OCSF classes that describe network egress. Everything else (process,
# config, lifecycle events) has no destination and must not become a row.
_NETWORK_CLASS_UIDS = frozenset({4001, 4002})

# OCSF disposition_id: 1 = Allowed, 2 = Blocked. 0 = Unknown.
_DISPOSITION_ALLOWED = 1
_DISPOSITION_BLOCKED = 2

# OpenShell writes this when no policy rule matched the request.
_NO_RULE = frozenset({"", "-", "none", "null"})

# Below this, an OCSF `time` value cannot be milliseconds: 1e11 seconds is
# year 5138, while 1e11 ms is 1973. So seconds and milliseconds are
# unambiguous on this threshold.
_MS_THRESHOLD = 1e11

# Marker OpenShell puts in front of a JSON record on stderr and in
# ``docker logs`` output: "<utc-timestamp> OCSF-JSON {...}".
_OCSF_STDERR_MARKER = "OCSF-JSON "


def _resolve_log_path(path: str | None) -> Path | None:
    """Resolve an explicit path or glob to the newest matching file."""
    candidate = path or AUDIT_LOG_PATH
    if any(character in candidate for character in "*?["):
        matches = sorted(glob.glob(candidate))
        if not matches:
            return None
        # Rotated files sort lexicographically by date, so the last is newest.
        return Path(matches[-1])
    resolved = Path(candidate)
    return resolved if resolved.exists() else None


def _extract_json_payload(line: str) -> str:
    """Return the JSON payload of a log line.

    Handles three shapes: a bare JSON object (the JSONL file), a line with the
    ``OCSF-JSON`` stderr marker, and anything else (returned unchanged so the
    caller's JSON parse fails and the line is skipped).
    """
    marker_at = line.find(_OCSF_STDERR_MARKER)
    if marker_at != -1:
        return line[marker_at + len(_OCSF_STDERR_MARKER) :].strip()
    return line


def read_egress_log(path: str | None = None) -> list[EgressRecord]:
    """Read egress records from the OpenShell audit layer.

    Returns an empty list when no log is present, which is the correct
    behaviour for a host with no sandbox: the dashboard shows an empty
    panel rather than inventing activity.

    Malformed, truncated, non-network, and unrecognised records are skipped
    individually so that one bad line cannot blank the whole panel.
    """
    log_path = _resolve_log_path(path)
    if log_path is None:
        return []

    records: list[EgressRecord] = []
    with log_path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(_extract_json_payload(line))
            except json.JSONDecodeError:
                continue
            try:
                records.append(_parse_ocsf_record(data))
            except (KeyError, TypeError, ValueError):
                # Includes pydantic ValidationError, e.g. an unknown decision.
                continue
    return records


def _parse_ocsf_record(data: dict) -> EgressRecord:
    """Parse one OCSF/audit record into an EgressRecord.

    Raises ValueError for records that carry no network destination or an
    unrecognised decision, so the caller can skip them.
    """
    if not isinstance(data, dict):
        raise ValueError("OCSF record is not a JSON object")

    class_uid = data.get("class_uid")
    if class_uid is not None and class_uid not in _NETWORK_CLASS_UIDS:
        raise ValueError(f"class_uid {class_uid!r} is not a network event")

    return EgressRecord(
        timestamp=_parse_timestamp(data),
        destination_host=_parse_destination(data),
        decision=_parse_decision(data),
        matched_policy=_parse_policy(data),
        bytes_out=_parse_bytes_out(data),
        request_count=_parse_request_count(data),
        simulated=bool(data.get("simulated", False)),
    )


def _parse_timestamp(data: dict) -> datetime:
    """OCSF ``time`` is epoch milliseconds; tolerate seconds and ISO strings."""
    raw = data.get("time")
    if raw is None:
        raw = data.get("timestamp")

    if isinstance(raw, bool):  # bool is an int subclass; never a timestamp
        raw = None
    if isinstance(raw, (int, float)):
        seconds = raw / 1000.0 if abs(raw) >= _MS_THRESHOLD else float(raw)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return datetime.now(timezone.utc)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    return datetime.now(timezone.utc)


def _parse_destination(data: dict) -> str:
    """Destination host, or 'unknown' when the record does not name one."""
    dst = data.get("dst_endpoint") or {}
    if not isinstance(dst, dict):
        dst = {}

    for key in ("domain", "hostname", "ip"):
        value = dst.get(key)
        if value:
            return str(value)

    flat = data.get("destination_host")
    return str(flat) if flat else "unknown"


def _parse_decision(data: dict) -> str:
    """Map OCSF disposition/action onto allowed|denied.

    Fail-safe by construction: only ``disposition_id == 1`` (Allowed) counts as
    allowed, and any *other* value that is present counts as denied. OCSF
    defines dispositions beyond 1 and 2 (Quarantined, Dropped, Logged, Other,
    ...); none of them means the traffic proceeded, and on a panel whose job is
    "what left this machine" a false "allowed" is the dangerous error.

    When ``disposition_id`` is absent entirely, fall back to the ``action``
    string and then to a flat ``decision`` key, so the simplified format works.
    """
    disposition_id = data.get("disposition_id")
    if disposition_id is not None:
        return "allowed" if disposition_id == _DISPOSITION_ALLOWED else "denied"

    action = data.get("action")
    if isinstance(action, str):
        lowered = action.strip().lower()
        if lowered == "allowed":
            return "allowed"
        if lowered in {"denied", "blocked"}:
            return "denied"

    # EgressRecord validates the value, so an unrecognised string is rejected
    # by the caller rather than silently guessed.
    return data.get("decision", "allowed")


def _parse_policy(data: dict) -> str | None:
    """The policy that matched, from firewall_rule.name, else policy.name."""
    firewall_rule = data.get("firewall_rule") or {}
    if isinstance(firewall_rule, dict):
        name = firewall_rule.get("name")
        if isinstance(name, str) and name.strip().lower() not in _NO_RULE:
            return name

    policy = data.get("policy") or {}
    if isinstance(policy, dict):
        name = policy.get("name")
        if isinstance(name, str) and name.strip().lower() not in _NO_RULE:
            return name

    flat = data.get("matched_policy")
    if isinstance(flat, str) and flat.strip().lower() not in _NO_RULE:
        return flat

    return None


def _parse_bytes_out(data: dict) -> int | None:
    """Bytes sent upstream, or None when omitted by the source event.

    OpenShell's published exemplar records omit byte counts, so None is
    normal -- never invent 0 bytes when the field was not recorded.
    """
    traffic = data.get("traffic") or {}
    if isinstance(traffic, dict):
        raw = traffic.get("bytes_out")
        if not isinstance(raw, bool) and isinstance(raw, (int, float)):
            return int(raw)
    flat = data.get("bytes_out")
    if not isinstance(flat, bool) and isinstance(flat, (int, float)):
        return int(flat)
    return None


def _parse_request_count(data: dict) -> int | None:
    """Requests represented by this record, or None when omitted.

    Never inferred from connection events when absent.
    """
    raw = data.get("request_count")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return max(1, int(raw))


def write_simulated_log(records: list[EgressRecord], path: str) -> None:
    """Write simulated egress records for development and testing.

    Production never calls this: records come from the enforcement layer.
    The output uses the simplified flat format, which read_egress_log accepts,
    and explicitly tags each record as ``simulated: true``.
    """
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        for record in records:
            entry = {
                "timestamp": record.timestamp.isoformat(),
                "destination_host": record.destination_host,
                "decision": record.decision,
                "matched_policy": record.matched_policy,
                "bytes_out": record.bytes_out,
                "request_count": record.request_count,
                "simulated": True,
            }
            handle.write(json.dumps(entry) + "\n")


def evidence_status(records: list[EgressRecord]) -> Literal["real", "simulated", "unavailable"]:
    """Report whether egress records are real OpenShell logs, simulated, or absent."""
    if not records:
        return "unavailable"
    if all(r.simulated for r in records):
        return "simulated"
    return "real"


def summarize_egress(records: list[EgressRecord]) -> dict:
    """Summarize egress records for the dashboard.

    Counts allowed and denied *requests* (not log lines) grouped by
    destination, and lists the policies that matched each destination.
    """
    by_dest: dict[str, dict] = {}
    total_allowed = 0
    total_denied = 0

    for record in records:
        host = record.destination_host
        if host not in by_dest:
            by_dest[host] = {
                "host": host,
                "allowed": 0,
                "denied": 0,
                "bytes_out": 0,
                "policies": set(),
            }
        entry = by_dest[host]
        if record.decision == "allowed":
            entry["allowed"] += record.request_count or 1
            total_allowed += record.request_count or 1
        else:
            entry["denied"] += record.request_count or 1
            total_denied += record.request_count or 1
        entry["bytes_out"] += record.bytes_out or 0
        if record.matched_policy:
            entry["policies"].add(record.matched_policy)

    destinations = []
    for entry in by_dest.values():
        entry["policies"] = sorted(entry["policies"])
        destinations.append(entry)

    return {
        "total_allowed": total_allowed,
        "total_denied": total_denied,
        "destinations": sorted(destinations, key=lambda d: d["host"]),
    }
