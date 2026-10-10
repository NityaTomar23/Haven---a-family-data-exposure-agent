"""Pydantic data models for the Haven pipeline.

Exact shapes from §5 of the spec — the dashboard depends on them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Identifier(BaseModel):
    """A single piece of personal information to search for."""

    kind: Literal[
        "name", "phone", "email", "address", "city_state", "alias", "school"
    ]
    value: str
    sensitivity: Literal["low", "high"]  # "high" must never leave the sandbox


class Exposure(BaseModel):
    """A discovered instance of personal data on a broker / people-search site."""

    id: str
    source_url: str
    source_name: str
    broker_type: Literal[
        "people_search", "data_broker", "breach_dump", "social", "other"
    ]
    matched_identifiers: list[Identifier]
    confidence: float = Field(ge=0, le=1)
    evidence_snippet: str  # short quote from the page, no full PII
    found_at: datetime


class RemovalProcedure(BaseModel):
    """How to request removal from a specific site."""

    exposure_id: str
    method: Literal["web_form", "email", "postal", "phone", "manual_only"]
    action_url: str | None = None
    required_evidence: list[str]
    statutory_deadline_days: int | None = None
    jurisdiction: str | None = None
    steps: list[str]
    source_url: str  # where the procedure was read from


class RemovalAction(BaseModel):
    """A drafted (or sent) removal request for a specific exposure."""

    id: str
    exposure_id: str
    procedure: RemovalProcedure
    draft: str
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
    """Network egress event from the enforcement layer, NOT the agent."""

    timestamp: datetime
    destination_host: str
    decision: Literal["allowed", "denied"]
    matched_policy: str | None = None
    bytes_out: int
    request_count: int


class TierUsage(BaseModel):
    """Per-call token/latency record for model-tiering analysis."""

    model: str
    tier: Literal["nano", "super", "ultra"]
    input_tokens: int
    output_tokens: int
    latency_ms: float
    purpose: str
    timestamp: datetime


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
    exposures: list[Exposure] = []
    procedures: list[RemovalProcedure] = []
    actions: list[RemovalAction] = []
    egress_log: list[EgressRecord] = []
    tier_usage: list[TierUsage] = []
