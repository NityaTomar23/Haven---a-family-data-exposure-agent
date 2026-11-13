"""Tavily Search and Extract wrappers -- the agent's research mechanism.

Tavily is used for *generic* research only:

* a broker inventory, from fixed identifier-free queries
  (:data:`INVENTORY_QUERIES`);
* each broker's first-party opt-out procedure, searched by broker name.

No family identifier and no identifying listing URL is ever sent. Every query
and URL passes the payload gate (:mod:`haven.privacy`) before the client is
constructed; a protected term raises ``PayloadBlocked`` and nothing is sent.

Installed SDK: tavily-python 0.8.5, which exposes ``search``, ``extract``,
``crawl`` and ``map`` but no ``research`` method.
"""

from __future__ import annotations

import os
from typing import Any

from tavily import TavilyClient

from haven import privacy
from haven.offline import OfflineTavilyClient, provider_mode

# Fixed, identifier-free inventory queries. They describe a category of
# website, never a person.
INVENTORY_QUERIES: tuple[str, ...] = (
    "list of people search sites and data brokers with opt-out pages",
    "data broker registry people-search websites remove personal information",
)


def _get_client() -> Any:
    """Return a Tavily client, or the offline stand-in in offline mode."""
    if provider_mode() == "offline":
        return OfflineTavilyClient()
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY environment variable is not set. "
            "Copy .env.example to .env and add your key."
        )
    return TavilyClient(api_key=api_key)


def search_brokers(query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
    """Run a Tavily Search (``search_depth="advanced"``).

    The query is gated before dispatch; callers must pass generic text.
    """
    privacy.check("tavily.search", query)
    client = _get_client()
    response = client.search(
        query=query,
        search_depth="advanced",
        max_results=max_results,
    )
    return response.get("results", [])


def search_inventory(*, max_results: int = 10) -> list[dict[str, Any]]:
    """Generic broker-inventory research across :data:`INVENTORY_QUERIES`."""
    results: list[dict[str, Any]] = []
    for query in INVENTORY_QUERIES:
        results.extend(search_brokers(query, max_results=max_results))
    return results


def search_optout_procedure(site_name: str) -> list[dict[str, Any]]:
    """Search for a broker's opt-out procedure. *site_name* is a company name."""
    query = f"{site_name} opt-out removal procedure how to remove personal data"
    return search_brokers(query, max_results=5)


def extract_page(url: str) -> dict[str, Any]:
    """Extract clean content from a (generic, first-party) URL via Tavily Extract.

    Returns the first result, or ``{"raw_content": "", "url": url}``.
    """
    privacy.check("tavily.extract", url)
    client = _get_client()
    response = client.extract(urls=[url])
    results = response.get("results", [])
    if results:
        return results[0]
    return {"raw_content": "", "url": url}


def extract_pages(urls: list[str]) -> list[dict[str, Any]]:
    """Extract several URLs in one Tavily call."""
    if not urls:
        return []
    privacy.check("tavily.extract", *urls)
    client = _get_client()
    response = client.extract(urls=urls)
    return response.get("results", [])
