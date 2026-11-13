"""Tavily Search and Extract wrappers.

Tavily is the agent's research mechanism and is load-bearing for the
submission, so the wrappers are tested directly against a faked
``TavilyClient`` rather than only being exercised through the pipeline.

The conftest ``no_network`` fixture replaces ``haven.research._get_client``
with a hard failure so an un-mocked call cannot reach the wire. This module
puts the *real* factory back and fakes the SDK instead, which is what lets the
missing-key path be tested for real.
"""

from __future__ import annotations

from typing import Any

import pytest

from haven import research

# Captured at import time, before conftest's autouse fixture patches the module.
_REAL_GET_CLIENT = research._get_client


class FakeTavilyClient:
    """Stands in for tavily.TavilyClient, recording every call."""

    def __init__(
        self,
        *,
        search_response: dict[str, Any] | None = None,
        extract_response: dict[str, Any] | None = None,
    ) -> None:
        self.api_key: str | None = None
        self.search_calls: list[tuple[str, dict[str, Any]]] = []
        self.extract_calls: list[tuple[Any, dict[str, Any]]] = []
        self._search_response = search_response or {"results": []}
        self._extract_response = extract_response or {"results": []}

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        self.search_calls.append((query, kwargs))
        return self._search_response

    def extract(self, urls: Any, **kwargs: Any) -> dict[str, Any]:
        self.extract_calls.append((urls, kwargs))
        return self._extract_response


@pytest.fixture
def tavily(monkeypatch):
    """Install the real factory plus a faked SDK client."""

    def _install(
        *,
        search_response: dict[str, Any] | None = None,
        extract_response: dict[str, Any] | None = None,
        api_key: str | None = "test-tavily-key",
    ) -> FakeTavilyClient:
        monkeypatch.setenv("HAVEN_PROVIDER_MODE", "live")
        monkeypatch.setattr(research, "_get_client", _REAL_GET_CLIENT)
        if api_key is None:
            monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        else:
            monkeypatch.setenv("TAVILY_API_KEY", api_key)

        client = FakeTavilyClient(
            search_response=search_response, extract_response=extract_response
        )
        monkeypatch.setattr(
            research, "TavilyClient", lambda api_key=None: _bind(client, api_key)
        )
        return client

    return _install


def _bind(client: FakeTavilyClient, api_key: str | None) -> FakeTavilyClient:
    client.api_key = api_key
    return client


# ── Client construction ────────────────────────────────────────────────


def test_missing_api_key_raises_a_named_error(tavily):
    tavily(api_key=None)

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        research.search_brokers("anything")


def test_all_wrappers_raise_without_a_key(tavily):
    tavily(api_key=None)

    for call in (
        lambda: research.search_brokers("q"),
        lambda: research.search_optout_procedure("Spokeo"),
        lambda: research.extract_page("https://example.test"),
        lambda: research.extract_pages(["https://example.test"]),
    ):
        with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
            call()


def test_client_receives_the_api_key(tavily):
    client = tavily(api_key="secret-key", search_response={"results": []})

    research.search_brokers("q")

    assert client.api_key == "secret-key"


# ── Search ─────────────────────────────────────────────────────────────


def test_search_brokers_returns_the_results_list(tavily):
    results = [{"url": "https://a.test", "title": "A", "content": "c"}]
    tavily(search_response={"results": results})

    assert research.search_brokers("q") == results


def test_search_brokers_uses_advanced_depth(tavily):
    """Advanced depth is what makes the evidence per source usable."""
    client = tavily(search_response={"results": []})

    research.search_brokers("q")

    _, kwargs = client.search_calls[0]
    assert kwargs["search_depth"] == "advanced"


def test_search_brokers_forwards_max_results(tavily):
    client = tavily(search_response={"results": []})

    research.search_brokers("q", max_results=3)

    _, kwargs = client.search_calls[0]
    assert kwargs["max_results"] == 3


def test_search_brokers_defaults_to_ten_results(tavily):
    client = tavily(search_response={"results": []})

    research.search_brokers("q")

    _, kwargs = client.search_calls[0]
    assert kwargs["max_results"] == 10


def test_search_brokers_tolerates_a_response_without_results(tavily):
    tavily(search_response={})

    assert research.search_brokers("q") == []


def test_search_brokers_passes_the_query_through_unchanged(tavily):
    """The wrapper must not rewrite generic queries."""
    client = tavily(search_response={"results": []})

    research.search_brokers("data broker opt-out procedure")

    assert client.search_calls[0][0] == "data broker opt-out procedure"


def test_search_inventory_issues_fixed_generic_queries(tavily):
    client = tavily(search_response={"results": []})

    research.search_inventory(max_results=4)

    assert len(client.search_calls) == len(research.INVENTORY_QUERIES)
    assert [q for q, _ in client.search_calls] == list(research.INVENTORY_QUERIES)
    assert all(kw["max_results"] == 4 for _, kw in client.search_calls)


# ── Opt-out procedure search ───────────────────────────────────────────


def test_optout_search_names_the_site_and_its_purpose(tavily):
    client = tavily(search_response={"results": []})

    research.search_optout_procedure("Spokeo")

    query = client.search_calls[0][0]
    assert "Spokeo" in query
    assert "opt-out" in query


def test_optout_search_is_capped_at_five_results(tavily):
    client = tavily(search_response={"results": []})

    research.search_optout_procedure("Spokeo")

    assert client.search_calls[0][1]["max_results"] == 5


# ── Extract ────────────────────────────────────────────────────────────


def test_extract_page_returns_the_first_result(tavily):
    payload = [{"url": "https://a.test", "raw_content": "full text"}]
    client = tavily(extract_response={"results": payload})

    assert research.extract_page("https://a.test") == payload[0]
    assert client.extract_calls[0][0] == ["https://a.test"]


def test_extract_page_degrades_to_an_empty_body(tavily):
    """A failed extraction must not raise: the pipeline falls back to the
    search snippet."""
    tavily(extract_response={"results": [], "failed_results": [{"url": "x"}]})

    assert research.extract_page("https://a.test") == {
        "raw_content": "",
        "url": "https://a.test",
    }


def test_extract_pages_short_circuits_on_no_urls(tavily):
    client = tavily(extract_response={"results": []})

    assert research.extract_pages([]) == []
    assert client.extract_calls == []


def test_extract_pages_batches_every_url_in_one_call(tavily):
    payload = [{"url": "https://a.test"}, {"url": "https://b.test"}]
    client = tavily(extract_response={"results": payload})

    urls = ["https://a.test", "https://b.test"]
    assert research.extract_pages(urls) == payload
    assert len(client.extract_calls) == 1
    assert client.extract_calls[0][0] == urls


def test_extract_pages_tolerates_a_response_without_results(tavily):
    tavily(extract_response={})

    assert research.extract_pages(["https://a.test"]) == []


# ── No fabricating errors ──────────────────────────────────────────────


def test_search_does_not_swallow_sdk_failures(monkeypatch):
    """A 429 from Tavily is an operator problem and must surface, not be
    silently converted into an empty result set."""
    monkeypatch.setenv("HAVEN_PROVIDER_MODE", "live")
    monkeypatch.setattr(research, "_get_client", _REAL_GET_CLIENT)
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")

    class Exploding:
        def search(self, *args, **kwargs):
            raise RuntimeError("tavily 429")

    monkeypatch.setattr(research, "TavilyClient", lambda api_key=None: Exploding())

    with pytest.raises(RuntimeError, match="429"):
        research.search_brokers("q")
