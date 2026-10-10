"""Tavily search and extract wrappers for the Haven research pipeline.

These are the agent's research mechanism — they make runtime calls to
Tavily Search and Tavily Extract.  This is load-bearing for the Tavily
bonus ($3,000 Best Use of Tavily).
"""

from __future__ import annotations

import os
from typing import Any

from tavily import TavilyClient


def _get_client() -> TavilyClient:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY environment variable is not set. "
            "Copy .env.example to .env and add your key."
        )
    return TavilyClient(api_key=api_key)


def search_brokers(query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
    """Search for data-broker / people-search listings using Tavily Search.

    Uses ``search_depth="advanced"`` per Tavily best-practices for
    stronger evidence per source.

    Returns the ``results`` list from the Tavily Search response.
    """
    client = _get_client()
    response = client.search(
        query=query,
        search_depth="advanced",
        max_results=max_results,
    )
    return response.get("results", [])


def search_optout_procedure(site_name: str) -> list[dict[str, Any]]:
    """Search for the opt-out / removal procedure for a specific site.

    Returns search results focused on how to remove data from the named
    broker or people-search site.
    """
    query = f"{site_name} opt-out removal procedure how to remove personal data"
    return search_brokers(query, max_results=5)


def extract_page(url: str) -> dict[str, Any]:
    """Extract clean content from a URL using Tavily Extract.

    Returns the extraction result dict with ``raw_content`` and
    ``results`` keys.
    """
    client = _get_client()
    response = client.extract(urls=[url])
    # The extract endpoint returns {"results": [...], "failed_results": [...]}
    results = response.get("results", [])
    if results:
        return results[0]
    return {"raw_content": "", "url": url}


def extract_pages(urls: list[str]) -> list[dict[str, Any]]:
    """Extract clean content from multiple URLs in a single Tavily call.

    Returns a list of extraction results.
    """
    if not urls:
        return []
    client = _get_client()
    response = client.extract(urls=urls)
    return response.get("results", [])
