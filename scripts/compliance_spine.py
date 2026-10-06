"""Minimal fixed-input connectivity check for Nebius Token Factory and Tavily."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI
from tavily import TavilyClient


MODEL = "nvidia/nemotron-3-super-120b-a12b"
TOKEN_FACTORY_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
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

    llm = OpenAI(
        base_url=TOKEN_FACTORY_BASE_URL,
        api_key=nebius_api_key,
    )
    completion = llm.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "This is a provider connectivity check. Do not request or infer personal information.",
            },
            {
                "role": "user",
                "content": "Reply with a short confirmation that the Haven demo model connection works.",
            },
        ],
    )

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
