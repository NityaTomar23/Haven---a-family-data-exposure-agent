"""Haven pipeline: discover → extract → draft → track.

Orchestrates the full data-exposure research and removal-drafting flow
using tiered Nemotron models and Tavily research.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from haven import llm, research
from haven.models import (
    Exposure,
    Family,
    Identifier,
    PipelineState,
    RemovalAction,
    RemovalProcedure,
)
from haven.seed import get_all_identifiers, get_search_identifiers


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())[:8]


# ── Stage 1: Discover exposures ────────────────────────────────────────

# Well-known people-search / data-broker sites to probe
KNOWN_BROKERS = [
    "Spokeo",
    "BeenVerified",
    "Whitepages",
    "TruePeopleSearch",
    "FastPeopleSearch",
    "Intelius",
    "PeopleFinder",
    "Radaris",
    "USSearch",
    "ZabaSearch",
    "AnyWho",
    "ThatsThem",
    "PublicRecordsNow",
    "Pipl",
    "MyLife",
]


def discover_exposures(
    family: Family,
    *,
    relevance_threshold: float = 0.3,
    max_search_results: int = 10,
) -> list[Exposure]:
    """Search for the family's data on broker / people-search sites.

    Uses Tavily Search (load-bearing runtime call) to find candidate
    listings, then uses the Nano tier to classify relevance.

    Only low-sensitivity identifiers are sent as search queries; high-
    sensitivity identifiers are used for matching against returned
    results only.
    """
    search_ids = get_search_identifiers(family)
    all_ids = get_all_identifiers(family)
    exposures: list[Exposure] = []

    # Build search queries from low-sensitivity identifiers
    for ident in search_ids:
        if ident.kind == "name":
            queries = [
                f'"{ident.value}" people search',
                f'"{ident.value}" public records',
            ]
        elif ident.kind == "city_state":
            # Combine with names for more targeted search
            names = [i.value for i in search_ids if i.kind == "name"]
            queries = [f'"{n}" {ident.value} data broker' for n in names[:2]]
        elif ident.kind == "alias":
            queries = [f'"{ident.value}" people search']
        else:
            continue

        for query in queries:
            results = research.search_brokers(
                query, max_results=max_search_results
            )
            for result in results:
                exposure = _classify_result(
                    result, all_ids, relevance_threshold
                )
                if exposure is not None:
                    exposures.append(exposure)

    # Deduplicate by source_url
    seen_urls: set[str] = set()
    unique: list[Exposure] = []
    for exp in exposures:
        if exp.source_url not in seen_urls:
            seen_urls.add(exp.source_url)
            unique.append(exp)

    return unique


def _classify_result(
    result: dict[str, Any],
    identifiers: list[Identifier],
    threshold: float,
) -> Exposure | None:
    """Use Nano tier to classify whether a search result is relevant.

    Returns an Exposure if the result is above the relevance threshold,
    or None if it should be discarded.
    """
    url = result.get("url", "")
    title = result.get("title", "")
    content = result.get("content", "")
    snippet = content[:500] if content else ""

    # Build identifier context for the model (no high-sensitivity values
    # are sent — only kinds and low-sensitivity values)
    id_context = "\n".join(
        f"- {i.kind}: {i.value if i.sensitivity == 'low' else '[REDACTED]'}"
        for i in identifiers
    )

    prompt = f"""Analyze this search result and determine if it likely contains personal data listings from a data broker or people-search site.

Search result:
Title: {title}
URL: {url}
Snippet: {snippet}

Family identifiers to match (REDACTED values are high-sensitivity):
{id_context}

Respond with ONLY a JSON object:
{{"relevant": true/false, "confidence": 0.0-1.0, "broker_type": "people_search"|"data_broker"|"breach_dump"|"social"|"other", "source_name": "site name", "evidence": "brief reason"}}"""

    try:
        response = llm.complete(
            tier="nano",
            system="You are a data-exposure classifier. Respond with only valid JSON.",
            user=prompt,
            purpose="classify_search_result",
            temperature=0.1,
            max_tokens=256,
        )

        # Parse JSON from response
        parsed = _extract_json(response)
        if not parsed.get("relevant", False):
            return None

        confidence = float(parsed.get("confidence", 0))
        if confidence < threshold:
            return None

        # Build matched identifiers (only the low-sensitivity ones that
        # appear to match)
        matched = [i for i in identifiers if i.sensitivity == "low"]

        return Exposure(
            id=_uid(),
            source_url=url,
            source_name=parsed.get("source_name", title),
            broker_type=parsed.get("broker_type", "other"),
            matched_identifiers=matched[:3],  # Keep it concise
            confidence=min(confidence, 1.0),
            evidence_snippet=parsed.get("evidence", snippet[:200]),
            found_at=_now(),
        )
    except Exception:
        return None


# ── Stage 2: Extract opt-out procedures ────────────────────────────────


def extract_optout_procedures(
    exposures: list[Exposure],
) -> list[RemovalProcedure]:
    """For each exposure, find and extract the opt-out/removal procedure.

    Uses Tavily Search to find the opt-out page, Tavily Extract to read
    it, and the Super tier to synthesize the procedure.
    """
    procedures: list[RemovalProcedure] = []

    for exposure in exposures:
        procedure = _extract_single_procedure(exposure)
        if procedure is not None:
            procedures.append(procedure)

    return procedures


def _extract_single_procedure(exposure: Exposure) -> RemovalProcedure | None:
    """Extract the opt-out procedure for a single exposure site."""
    site_name = exposure.source_name

    # Step 1: Search for the opt-out procedure (Tavily Search)
    search_results = research.search_optout_procedure(site_name)
    if not search_results:
        return _fallback_procedure(exposure)

    # Step 2: Extract content from the most relevant result (Tavily Extract)
    best_url = search_results[0].get("url", "")
    try:
        extracted = research.extract_page(best_url)
        page_content = extracted.get("raw_content", "")[:3000]
    except Exception:
        page_content = search_results[0].get("content", "")

    # Step 3: Use Super tier to synthesize the procedure
    prompt = f"""Analyze this page content and extract the opt-out / data removal procedure for {site_name}.

Page content:
{page_content}

Respond with ONLY a JSON object:
{{
  "method": "web_form"|"email"|"postal"|"phone"|"manual_only",
  "action_url": "URL or null",
  "required_evidence": ["list of required documents/info"],
  "statutory_deadline_days": number or null,
  "jurisdiction": "applicable law" or null,
  "steps": ["step 1", "step 2", ...]
}}"""

    try:
        response = llm.complete(
            tier="super",
            system="You are a privacy-procedure analyst. Extract structured removal procedures. Respond with only valid JSON.",
            user=prompt,
            purpose="extract_optout_procedure",
            temperature=0.2,
            max_tokens=1024,
        )
        parsed = _extract_json(response)

        return RemovalProcedure(
            exposure_id=exposure.id,
            method=parsed.get("method", "manual_only"),
            action_url=parsed.get("action_url"),
            required_evidence=parsed.get("required_evidence", []),
            statutory_deadline_days=parsed.get("statutory_deadline_days"),
            jurisdiction=parsed.get("jurisdiction"),
            steps=parsed.get("steps", ["Visit the site and follow their opt-out process"]),
            source_url=best_url,
        )
    except Exception:
        return _fallback_procedure(exposure)


def _fallback_procedure(exposure: Exposure) -> RemovalProcedure:
    """Create a manual-only procedure when automated extraction fails."""
    return RemovalProcedure(
        exposure_id=exposure.id,
        method="manual_only",
        action_url=exposure.source_url,
        required_evidence=["Government-issued ID (optional)", "Proof of address"],
        statutory_deadline_days=None,
        jurisdiction=None,
        steps=[
            f"Visit {exposure.source_url}",
            "Look for 'Opt-Out', 'Remove My Info', or 'Privacy' link",
            "Follow the site's removal instructions",
            "Record confirmation number if provided",
        ],
        source_url=exposure.source_url,
    )


# ── Stage 3: Draft removal requests ───────────────────────────────────


def draft_removal_requests(
    family: Family,
    exposures: list[Exposure],
    procedures: list[RemovalProcedure],
) -> list[RemovalAction]:
    """Draft a removal request for each exposure/procedure pair.

    Uses the Super tier for individual drafts, Ultra tier for multi-site
    strategy synthesis when there are many sites.
    """
    # Build a procedure lookup
    proc_map = {p.exposure_id: p for p in procedures}

    # Decide tier: Ultra for multi-site strategy (5+ sites), Super otherwise
    use_ultra = len(exposures) >= 5

    actions: list[RemovalAction] = []
    for exposure in exposures:
        procedure = proc_map.get(exposure.id)
        if procedure is None:
            continue

        draft = _draft_single_request(
            family, exposure, procedure, use_ultra=use_ultra
        )
        actions.append(draft)

    return actions


def _draft_single_request(
    family: Family,
    exposure: Exposure,
    procedure: RemovalProcedure,
    *,
    use_ultra: bool = False,
) -> RemovalAction:
    """Draft a removal request for a single exposure."""
    tier: llm.Tier = "ultra" if use_ultra else "super"
    purpose = "draft_removal_multi_site" if use_ultra else "draft_removal_single"

    # Use only parent names (never children's names in outbound content)
    parents = [m for m in family.members if m.role == "parent"]
    requestor_name = f"{parents[0].first_name} {parents[0].last_name}" if parents else "The Data Subject"

    prompt = f"""Draft a data removal / opt-out request for the following site.

Site: {exposure.source_name}
URL: {exposure.source_url}
Removal method: {procedure.method}
Steps: {json.dumps(procedure.steps)}
Required evidence: {json.dumps(procedure.required_evidence)}
Jurisdiction: {procedure.jurisdiction or 'Not specified'}

Requestor: {requestor_name}

Write a professional, firm removal request. Include:
1. Clear identification of the request (data removal)
2. Reference to applicable privacy law if jurisdiction is known
3. Specific data to be removed (mention the listing URL)
4. Deadline reference if statutory deadline applies
5. Contact info placeholder [PHONE] and [EMAIL] for the human to fill in

Do NOT include children's names or any high-sensitivity data.
The request must be a DRAFT for human review — clearly mark it as such."""

    try:
        draft_text = llm.complete(
            tier=tier,
            system="You are a privacy attorney's assistant drafting data removal requests. Be professional, cite applicable law, and clearly mark the output as a draft for human review.",
            user=prompt,
            purpose=purpose,
            temperature=0.3,
            max_tokens=1500,
        )
    except Exception as exc:
        draft_text = f"[Draft generation failed: {exc}. Please compose manually using the procedure steps above.]"

    return RemovalAction(
        id=_uid(),
        exposure_id=exposure.id,
        procedure=procedure,
        draft=draft_text,
        status="drafted",
        drafted_model=llm.model_for(tier),
        created_at=_now(),
        updated_at=_now(),
    )


# ── Full pipeline ──────────────────────────────────────────────────────


def run_pipeline(
    family: Family,
    *,
    relevance_threshold: float = 0.3,
    max_search_results: int = 10,
) -> PipelineState:
    """Run the full discover → extract → draft pipeline.

    Returns a PipelineState ready for the dashboard.

    ``tier_usage`` covers only the calls this run made. The usage log is
    module-global so that the dashboard's chart can show all activity; taking a
    slice keeps a second run from reporting the first run's tokens as its own.
    """
    usage_mark = len(llm.get_usage_log())

    # Stage 1: Discover
    exposures = discover_exposures(
        family,
        relevance_threshold=relevance_threshold,
        max_search_results=max_search_results,
    )

    # Stage 2: Extract procedures
    procedures = extract_optout_procedures(exposures)

    # Stage 3: Draft removal requests
    actions = draft_removal_requests(family, exposures, procedures)

    return PipelineState(
        family=family,
        exposures=exposures,
        procedures=procedures,
        actions=actions,
        tier_usage=llm.get_usage_log()[usage_mark:],
    )


# ── Status transitions ────────────────────────────────────────────────


def approve_action(action: RemovalAction) -> RemovalAction:
    """Transition a drafted action to 'approved' (human confirmed)."""
    if action.status != "drafted":
        raise ValueError(f"Cannot approve action in status '{action.status}'")
    action.status = "approved"
    action.updated_at = _now()
    return action


def mark_sent(action: RemovalAction) -> RemovalAction:
    """Transition an approved action to 'sent' (human confirmed sending).

    This requires prior human approval — no automated submission.
    """
    if action.status != "approved":
        raise ValueError(
            f"Cannot mark as sent: action must be 'approved', got '{action.status}'. "
            "Human approval is required before marking as sent."
        )
    action.status = "sent"
    action.updated_at = _now()
    return action


def mark_confirmed(action: RemovalAction) -> RemovalAction:
    """Transition a sent action to 'confirmed_removed'."""
    if action.status != "sent":
        raise ValueError(f"Cannot confirm removal: action must be 'sent', got '{action.status}'")
    action.status = "confirmed_removed"
    action.updated_at = _now()
    return action


# ── JSON extraction helper ─────────────────────────────────────────────


def _extract_json(text: str) -> dict:
    """Extract a JSON object from LLM output that might contain markdown
    fences or preamble text."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown code block
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    # Try finding { ... } substring
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}
