"""Minimal fixed-input connectivity check for Nebius Token Factory and Tavily."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from tavily import TavilyClient

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from haven import llm, privacy  # noqa: E402


MODEL = llm.model_for("super")
TAVILY_QUERY = "data broker opt-out procedure"


def main() -> int:
    load_dotenv()
    nebius_api_key = os.getenv("NEBIUS_API_KEY")
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    missing = [
        name
        for name, value in (
            ("NEBIUS_API_KEY", nebius_api_key),
            ("TAVILY_API_KEY", tavily_api_key),
        )
        if not value
    ]
    if missing:
        print(
            "Missing required environment variable(s): " + ", ".join(missing),
            file=sys.stderr,
        )
        return 2

    endpoint = llm.base_url()
    system_prompt = (
        "This is a provider connectivity check. "
        "Do not request or infer personal information."
    )
    user_prompt = (
        "Reply with a short confirmation that the Haven demo model connection works."
    )
    privacy.check("token_factory", system_prompt, user_prompt)
    privacy.check("tavily.search", TAVILY_QUERY)

    client = OpenAI(
        base_url=endpoint,
        api_key=nebius_api_key,
    )
    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    print(f"Endpoint: {endpoint}")
    print(f"Nebius Token Factory ({completion.model})")
    print(completion.choices[0].message.content or "(empty response)")
    if completion.usage is not None:
        print(
            "Tokens: "
            f"{completion.usage.prompt_tokens} input, "
            f"{completion.usage.completion_tokens} output"
        )

    search = TavilyClient(api_key=tavily_api_key).search(
        TAVILY_QUERY,
        max_results=3,
    )
    print(f"\nTavily Search ({TAVILY_QUERY})")
    results = search.get("results", [])
    if not results:
        print("No results returned.")
    for result in results:
        title = result.get("title") or "Untitled result"
        url = result.get("url") or "(no URL)"
        content = " ".join((result.get("content") or "").split())
        excerpt = content[:240] + ("…" if len(content) > 240 else "")
        print(f"- {title}\n  {url}\n  {excerpt}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
