"""Offline providers: deterministic stand-ins for the Tavily and OpenAI SDKs.

Used when Haven runs without API keys (``HAVEN_PROVIDER_MODE=auto`` with no
keys, or ``=offline``). They let a judge or a reviewer click through the whole
workflow on the public demo without spending provider credit.

Two rules keep this honest:

1. Offline output is always labelled. Tier-usage rows carry
   ``simulated=True`` and the dashboard shows an "offline providers" banner.
2. Offline clients sit *behind* the payload gate, exactly where the real SDKs
   sit, so the privacy checks run identically in both modes.

Nothing here touches the network.
"""

from __future__ import annotations

import json
import os
import re
from types import SimpleNamespace
from typing import Any, Literal

ProviderMode = Literal["live", "offline"]

OFFLINE_HOST = "https://offline.haven.example"

# Generic broker knowledge the offline Tavily returns. Real company names,
# fictional URLs: nothing here claims to be a live search result.
_BROKERS: dict[str, dict[str, Any]] = {
    "Spokeo": {"type": "people_search", "method": "web_form", "target": None},
    "Whitepages": {"type": "people_search", "method": "web_form", "target": None},
    "Radaris": {"type": "data_broker", "method": "web_form", "target": None},
    "FastPeopleSearch": {"type": "people_search", "method": "web_form", "target": None},
    "BeenVerified": {"type": "people_search", "method": "web_form", "target": None},
    "TruePeopleSearch": {"type": "people_search", "method": "web_form", "target": None},
    "Intelius": {"type": "data_broker", "method": "email", "target": 30},
    "MyLife": {"type": "people_search", "method": "email", "target": None},
    "PeopleFinders": {"type": "people_search", "method": "web_form", "target": None},
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def provider_mode() -> ProviderMode:
    """Resolve the provider mode from ``HAVEN_PROVIDER_MODE``.

    ``live`` and ``offline`` are explicit. ``auto`` (the default) is live only
    when both API keys are present, so a fresh clone works out of the box.
    """
    requested = os.environ.get("HAVEN_PROVIDER_MODE", "auto").strip().lower()
    if requested in ("live", "offline"):
        return requested  # type: ignore[return-value]
    has_keys = bool(os.environ.get("NEBIUS_API_KEY")) and bool(
        os.environ.get("TAVILY_API_KEY")
    )
    return "live" if has_keys else "offline"


# ── Tavily stand-in ─────────────────────────────────────────────────────


class OfflineTavilyClient:
    """Mimics the subset of ``tavily.TavilyClient`` Haven uses."""

    offline = True

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        max_results = int(kwargs.get("max_results", 10))
        lowered = query.lower()
        for name in _BROKERS:
            if lowered.startswith(name.lower()):
                slug = _slug(name)
                return {
                    "results": [
                        {
                            "url": f"{OFFLINE_HOST}/{slug}/opt-out",
                            "title": f"{name} — How to opt out (offline sample)",
                            "content": f"Steps to remove a listing from {name}.",
                        }
                    ][:max_results]
                }
        results = [
            {
                "url": f"{OFFLINE_HOST}/inventory/{_slug(name)}",
                "title": f"{name} — people-search and data-broker site",
                "content": (
                    f"{name} is a {info['type'].replace('_', ' ')} site that "
                    "aggregates public records and offers an opt-out process."
                ),
            }
            for name, info in _BROKERS.items()
        ]
        return {"results": results[:max_results]}

    def extract(self, urls: Any, **kwargs: Any) -> dict[str, Any]:
        urls = [urls] if isinstance(urls, str) else list(urls)
        results = []
        for url in urls:
            name = next(
                (n for n in _BROKERS if f"/{_slug(n)}/" in url), "the site"
            )
            info = _BROKERS.get(name, {"method": "web_form", "target": None})
            target = (
                f" Requests are processed within {info['target']} days."
                if info.get("target")
                else ""
            )
            results.append(
                {
                    "url": url,
                    "raw_content": (
                        f"{name} privacy center. To remove your information, "
                        f"use the {info['method'].replace('_', ' ')} opt-out. "
                        "Search for your listing, copy its URL, submit the "
                        "removal request, then confirm via the email link."
                        f"{target}"
                    ),
                }
            )
        return {"results": results, "failed_results": []}


# ── OpenAI stand-in ─────────────────────────────────────────────────────


def _usage(prompt: str, completion: str) -> SimpleNamespace:
    # Rough 4-characters-per-token estimate, clearly labelled as simulated.
    return SimpleNamespace(
        prompt_tokens=max(1, len(prompt) // 4),
        completion_tokens=max(1, len(completion) // 4),
    )


def _respond(system: str, user: str) -> str:
    lowered = system.lower()
    if "inventory classifier" in lowered:
        title = re.search(r"Title:\s*(.+)", user)
        name = (title.group(1) if title else "").split(" — ")[0].strip()
        if name in _BROKERS:
            return json.dumps(
                {
                    "is_broker": True,
                    "broker_name": name,
                    "broker_type": _BROKERS[name]["type"],
                    "confidence": 0.9,
                }
            )
        return json.dumps({"is_broker": False, "confidence": 0.1})
    if "procedure analyst" in lowered:
        site = re.search(r"procedure for (.+?)\.\n", user)
        name = site.group(1) if site else ""
        info = _BROKERS.get(name, {"method": "web_form", "target": None})
        return json.dumps(
            {
                "method": info["method"],
                "action_url": f"{OFFLINE_HOST}/{_slug(name)}/opt-out",
                "required_evidence": ["Listing URL", "Email address for confirmation"],
                "statutory_deadline_days": None,
                "deadline_source_url": None,
                "service_target_days": info.get("target"),
                "jurisdiction": None,
                "steps": [
                    "Open the site's opt-out page",
                    "Find the listing and copy its URL",
                    "Submit the removal request",
                    "Click the confirmation link the site emails you",
                ],
            }
        )
    if "removal strategist" in lowered:
        return (
            "OFFLINE SAMPLE STRATEGY (simulated, not model output)\n"
            "1. Start with the sites that expose a street address or phone number.\n"
            "2. Batch the web-form opt-outs in one sitting; they confirm by email.\n"
            "3. Re-check each site in 30 days; brokers often re-list from upstream sources."
        )
    if "drafting data removal requests" in lowered:
        site = re.search(r"Site:\s*(.+)", user)
        name = site.group(1).strip() if site else "the site"
        return (
            "DRAFT — FOR HUMAN REVIEW (offline sample, not model output)\n\n"
            f"To the {name} privacy team,\n\n"
            "I am requesting the removal of my personal information from your "
            "website. The listing is at [LISTING_URL]. My name is [FULL_NAME].\n\n"
            "Please delete this listing, suppress future re-listing, and confirm "
            "completion to [EMAIL].\n\n"
            "Sincerely,\n[FULL_NAME]\n[PHONE]"
        )
    return "OK (offline provider)"


class _Completions:
    def create(self, *, model: str, messages: list[dict[str, str]], **kwargs: Any):
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user = next((m["content"] for m in messages if m["role"] == "user"), "")
        content = _respond(system, user)
        return SimpleNamespace(
            model=model,
            usage=_usage(system + user, content),
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        )


class OfflineOpenAI:
    """Mimics the subset of ``openai.OpenAI`` Haven uses."""

    offline = True

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_Completions())
        self.models = SimpleNamespace(list=lambda: [])

