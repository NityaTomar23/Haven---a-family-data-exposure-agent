"""Tiered Nemotron client with per-tier token/latency logging.

All inference goes through Nebius Token Factory using the OpenAI-compatible
API. No other inference endpoint is permitted in shipped code paths.

Model tiers:
  - nano  -> extraction, classification, routing. Every-turn calls.
  - super -> the workhorse: reasoning, drafting, planning.
  - ultra -> hard cases only: multi-site removal strategy, long context.

Provenance of the model ids (verified against the official Nebius cookbook,
models/nemotron/README.md, rather than assumed):

  - ``nvidia/nemotron-3-super-120b-a12b``      confirmed present
  - ``nvidia/Nemotron-3-Ultra-550b-a55b``      confirmed present
    (note the capitalisation: ``Nemotron-3-Ultra-550b-a55b``)
  - ``nvidia/nemotron-3-nano-30b``             UNVERIFIED -- this exact id
    does not appear in the cookbook. The 30B-class Nemotron listed there is
    ``nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`` (in the "not currently
    featured" block), and the featured small model is
    ``nvidia/Nemotron-3_5-Lightning``. Run ``scripts/verify_models.py``
    against a live key to settle it, then set NEBIUS_MODEL_NANO.

Base URL: the project brief mandates the region-specific
``https://api.tokenfactory.us-central1.nebius.com/v1/``. Nebius documents
that public endpoints are global and that a region-specific base URL "can
stop working if the endpoint's processing region changes". The regional URL
is therefore the default, and ``NEBIUS_BASE_URL`` overrides it to the
documented region-free host if the demo path breaks. Both hosts are
allowlisted in policy/policy.yaml.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Literal

from openai import OpenAI

from haven.models import TierUsage

# ── Endpoint configuration ─────────────────────────────────────────────

# The brief's mandated regional endpoint, used by default.
SPEC_REGIONAL_BASE_URL = "https://api.tokenfactory.us-central1.nebius.com/v1/"

# The region-free endpoint Nebius documents as the stable public entry point.
DOCUMENTED_GLOBAL_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"

# Every host the sandbox policy must allow. Keep in step with
# policy/policy.yaml; a host that is not allowlisted returns 403.
ALLOWED_TOKEN_FACTORY_BASE_URLS = (
    SPEC_REGIONAL_BASE_URL,
    DOCUMENTED_GLOBAL_BASE_URL,
)

# Retained for backwards compatibility with earlier imports.
TOKEN_FACTORY_BASE_URL = SPEC_REGIONAL_BASE_URL

# Hosts that must never appear as the shipped inference endpoint.
FORBIDDEN_INFERENCE_HOSTS = ("integrate.api.nvidia.com", "build.nvidia.com")

Tier = Literal["nano", "super", "ultra"]

# ── Model configuration ────────────────────────────────────────────────

TIER_MODELS: dict[str, str] = {
    "nano": "nvidia/nemotron-3-nano-30b",  # UNVERIFIED, see module docstring
    "super": "nvidia/nemotron-3-super-120b-a12b",
    "ultra": "nvidia/Nemotron-3-Ultra-550b-a55b",
}

# Environment overrides, one per tier, resolved at call time so that a
# .env file loaded after import is still honoured.
_TIER_ENV_VARS: dict[str, str] = {
    "nano": "NEBIUS_MODEL_NANO",
    "super": "NEBIUS_MODEL_SUPER",
    "ultra": "NEBIUS_MODEL_ULTRA",
}


def base_url() -> str:
    """Resolve the Token Factory base URL, honouring NEBIUS_BASE_URL."""
    return os.environ.get("NEBIUS_BASE_URL") or TOKEN_FACTORY_BASE_URL


def model_for(tier: Tier) -> str:
    """Resolve the model id for a tier, honouring the per-tier env override."""
    override = os.environ.get(_TIER_ENV_VARS[tier], "").strip()
    return override or TIER_MODELS[tier]


# ── In-memory usage log ────────────────────────────────────────────────
_usage_log: list[TierUsage] = []


def get_usage_log() -> list[TierUsage]:
    """Return the accumulated tier-usage records (read-only copy)."""
    return list(_usage_log)


def clear_usage_log() -> None:
    """Reset the usage log (useful in tests)."""
    _usage_log.clear()


# ── Client factory ─────────────────────────────────────────────────────

_client: OpenAI | None = None
_client_base_url: str | None = None


def _get_client() -> OpenAI:
    global _client, _client_base_url
    resolved = base_url()
    # Rebuild if the configured endpoint changed since the client was built.
    if _client is not None and _client_base_url != resolved:
        _client = None
    if _client is None:
        api_key = os.environ.get("NEBIUS_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "NEBIUS_API_KEY environment variable is not set. "
                "Copy .env.example to .env and add your key."
            )
        _client = OpenAI(base_url=resolved, api_key=api_key)
        _client_base_url = resolved
    return _client


def reset_client() -> None:
    """Force re-creation of the OpenAI client (e.g. after env change)."""
    global _client, _client_base_url
    _client = None
    _client_base_url = None


# ── Model verification ─────────────────────────────────────────────────


def verify_models() -> dict[str, dict]:
    """Check every tier's model id against the live /v1/models listing.

    This is the only way to settle an unverified id such as the nano tier.
    Requires NEBIUS_API_KEY. Returns a mapping of tier -> {model, available}
    plus an ``all_models`` key listing what the endpoint actually serves.
    """
    client = _get_client()
    available = {entry.id for entry in client.models.list()}

    result: dict[str, dict] = {}
    for tier in TIER_MODELS:
        model = model_for(tier)
        result[tier] = {"model": model, "available": model in available}
    result["all_models"] = {"available": sorted(available)}
    return result


# ── Core completion function ───────────────────────────────────────────


def complete(
    *,
    tier: Tier,
    system: str,
    user: str,
    purpose: str,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> str:
    """Send a chat completion request to the appropriate Nemotron tier.

    Records token counts and latency in the usage log for the dashboard
    tier-usage chart.

    Returns the assistant message content as a string.
    """
    model = model_for(tier)
    client = _get_client()

    start = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Extract usage metrics
    input_tokens = 0
    output_tokens = 0
    if response.usage:
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens

    _usage_log.append(
        TierUsage(
            model=model,
            tier=tier,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round(elapsed_ms, 1),
            purpose=purpose,
            timestamp=datetime.now(timezone.utc),
        )
    )

    content = response.choices[0].message.content or ""
    return content
