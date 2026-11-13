"""Pydantic data models for the Haven pipeline.

Shapes follow §5 of the project brief; the dashboard depends on them.
Sensitivity labels are metadata, not an enforcement control: *no* family
identifier -- low or high -- may be sent to a provider. That rule is enforced
by ``haven.privacy``, not by these labels.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BrokerType = Literal["people_search", "data_broker", "social", "other"]
MatchStatus = Literal["candidate", "verified", "rejected"]


class Identifier(BaseModel):
    """A single piece of personal information, used for LOCAL matching only."""

    kind: Literal["name", "phone", "email", "address", "city_state", "alias"]
    value: str
    sensitivity: Literal["low", "high"]  # labels do not authorise transmission


class Exposure(BaseModel):
    """A listing on a broker / people-search site, matched locally."""

    id: str
    source_url: str
    source_name: str
    broker_type: BrokerType
    matched_identifiers: list[Identifier]  # exact local matches only
    confidence: float = Field(ge=0, le=1)  # local match score; never verifies alone
    evidence_snippet: str  # redacted; no full PII
    found_at: datetime
    match_status: MatchStatus = "candidate"
    subject_member: int | None = None  # index into Family.members, local use only


class BrokerInventoryEntry(BaseModel):
    """A broker found by generic, identifier-free research."""

    name: str
    broker_type: BrokerType
    source_url: str  # the generic page that named the broker
    confidence: float = Field(ge=0, le=1)
    coverage: Literal["local_fixture", "manual_only"]
    # manual_only: checking this site would require submitting a family
    # identifier, which the privacy guarantee forbids. The parent checks it.


class RemovalProcedure(BaseModel):
    """How to request removal from a specific site."""

    exposure_id: str
    method: Literal["web_form", "email", "postal", "phone", "manual_only"]
    action_url: str | None = None
    required_evidence: list[str]
    statutory_deadline_days: int | None = None
    deadline_source_url: str | None = None
    deadline_verified_at: datetime | None = None
    service_target_days: int | None = None  # a site's own promise, not law
    jurisdiction: str | None = None
    steps: list[str]
    source_url: str  # where the procedure was read from
    retrieved_at: datetime | None = None


class RemovalAction(BaseModel):
    """A drafted removal request. 'sent' means the user attested to sending it;
    the app never submits anything to a third-party site."""

    id: str
    exposure_id: str
    procedure: RemovalProcedure
    draft: str  # contains placeholders; personal details are filled locally
    status: Literal[
        "drafted",
        "approved",
        "sent",
        "confirmed_removed",
        "rejected",
        "pending",
    ]
    drafted_model: str  # which Nemotron tier produced it
    created_at: datetime
    updated_at: datetime


class EgressRecord(BaseModel):
    """Enforcement metadata, NOT payload contents.

    OpenShell OCSF records describe destinations and decisions; they never
    establish what an allowed request body contained.
    """

    timestamp: datetime
    destination_host: str
    decision: Literal["allowed", "denied"]
    matched_policy: str | None = None
    bytes_out: int | None = None  # only when present in the source event
    request_count: int | None = None  # never inferred from connection events
    simulated: bool = False  # True for non-OCSF (development) records


class TierUsage(BaseModel):
    """Per-call token/latency record for model-tiering analysis."""

    model: str
    tier: Literal["nano", "super", "ultra"]
    input_tokens: int
    output_tokens: int
    latency_ms: float
    purpose: str
    timestamp: datetime
    simulated: bool = False  # True when produced by the offline provider


class FamilyMember(BaseModel):
    """A member of the synthetic family used for demos."""

    first_name: str
    last_name: str
    role: Literal["parent", "child"]
    age: int
    identifiers: list[Identifier]


class Family(BaseModel):
    """A complete synthetic family."""

    family_id: str
    members: list[FamilyMember]
    address: str
    city: str
    state: str
    zip_code: str
    created_at: datetime


class PipelineState(BaseModel):
    """Top-level state for the Haven pipeline — drives the dashboard."""

    family: Family
    inventory: list[BrokerInventoryEntry] = []
    exposures: list[Exposure] = []
    procedures: list[RemovalProcedure] = []
    actions: list[RemovalAction] = []
    egress_log: list[EgressRecord] = []
    tier_usage: list[TierUsage] = []
    strategy: str | None = None  # ultra-tier multi-site plan, identifier-free
    provider_mode: Literal["live", "offline"] = "live"
