"""Pydantic data models for the Haven pipeline and local encrypted vault.

Sensitivity labels are metadata, not an enforcement control: *no* family
identifier -- low or high -- may ever be sent to an LLM or search provider.
That rule is enforced by ``haven.boundary`` and ``haven.privacy``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BrokerType = Literal["people_search", "data_broker", "social", "other"]
MatchStatus = Literal["candidate", "verified", "rejected"]
OptOutMethod = Literal["web_form", "email", "postal", "phone", "account", "manual_only"]
ActionStatus = Literal[
    "drafted",
    "approved",
    "sent",
    "confirmed_removed",
    "re_listed",
    "follow_up_due",
    "rejected",
    "pending",
]


class Identifier(BaseModel):
    """A single piece of personal information, used for LOCAL matching and rendering only."""

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
    """A broker discovered from the local registry or identifier-free research."""

    name: str
    broker_type: BrokerType
    source_url: str  # the generic page or registry entry that named the broker
    confidence: float = Field(ge=0, le=1)
    coverage: Literal["local_fixture", "manual_only", "registry"]


class RemovalProcedure(BaseModel):
    """How to request removal from a specific site."""

    exposure_id: str
    method: OptOutMethod
    action_url: str | None = None
    optout_email: str | None = None
    required_evidence: list[str]
    required_fields: list[str] = Field(default_factory=list)
    verification_step: str | None = None
    statutory_deadline_days: int | None = None
    deadline_source_url: str | None = None
    deadline_verified_at: datetime | None = None
    service_target_days: int | None = None  # a site's own promise, not law
    re_list_days: int = 30
    jurisdiction: str | None = None
    steps: list[str]
    source_url: str  # where the procedure was read from
    retrieved_at: datetime | None = None


class DiffHunk(BaseModel):
    """A single placeholder substitution shown on the local diff review screen."""

    placeholder: str
    replacement: str
    field_kind: str


class RemovalAction(BaseModel):
    """A drafted removal request. 'sent' means the user attested to sending it;
    the app never submits anything to a third-party site."""

    id: str
    exposure_id: str
    procedure: RemovalProcedure
    draft: str  # contains placeholders; personal details are filled locally
    status: ActionStatus
    drafted_model: str
    created_at: datetime
    updated_at: datetime
    rendered_draft: str | None = None
    diff_hunks: list[DiffHunk] = Field(default_factory=list)
    mailto_uri: str | None = None
    form_fields: dict[str, str] = Field(default_factory=dict)
    sent_at: datetime | None = None
    confirmed_at: datetime | None = None
    due_at: datetime | None = None
    rescan_30d_at: datetime | None = None
    rescan_60d_at: datetime | None = None
    rescan_90d_at: datetime | None = None
    requires_parental_consent: bool = False
    parental_consent_confirmed: bool = False
    notes: str = ""


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
    """A member of a family stored in the local vault or synthetic demo."""

    first_name: str
    last_name: str
    role: Literal["parent", "child"]
    age: int = Field(ge=0, le=130)
    identifiers: list[Identifier]
    member_id: str = ""
    parental_consent_confirmed: bool = False

    @property
    def is_minor(self) -> bool:
        """Return True when the member is a minor (role == 'child' or age < 18)."""
        return self.role == "child" or self.age < 18


class Family(BaseModel):
    """A complete family profile."""

    family_id: str
    members: list[FamilyMember]
    address: str
    city: str
    state: str
    zip_code: str
    created_at: datetime
    jurisdiction: str = "CCPA"
    is_synthetic: bool = False


class BrokerSearchLink(BaseModel):
    """A locally generated search deep link for a data broker."""

    broker_slug: str
    broker_name: str
    member_name: str
    member_index: int
    is_minor: bool = False
    search_url: str
    optout_url: str
    optout_method: OptOutMethod


class PipelineState(BaseModel):
    """Top-level state for the Haven pipeline — drives the dashboard."""

    family: Family
    inventory: list[BrokerInventoryEntry] = Field(default_factory=list)
    exposures: list[Exposure] = Field(default_factory=list)
    procedures: list[RemovalProcedure] = Field(default_factory=list)
    actions: list[RemovalAction] = Field(default_factory=list)
    egress_log: list[EgressRecord] = Field(default_factory=list)
    tier_usage: list[TierUsage] = Field(default_factory=list)
    search_links: list[BrokerSearchLink] = Field(default_factory=list)
    strategy: str | None = None  # ultra-tier multi-site plan, identifier-free
    provider_mode: Literal["live", "offline"] = "live"
