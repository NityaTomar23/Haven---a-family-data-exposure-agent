# Haven

Haven is a prototype for finding public data exposure and preparing removal requests for human review. The first implementation increment is a provider connectivity check for Nebius Token Factory and Tavily Search. It uses only fixed, generic text and does not accept family identifiers.

## Run the compliance spine

Requirements: Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

1. Copy `.env.example` to `.env` and replace both placeholders with your own API keys.
2. Install the locked project dependencies with `uv sync`.
3. Run `uv run python scripts/compliance_spine.py`.

The script sends a fixed connectivity-check prompt to `nvidia/nemotron-3-super-120b-a12b` and a generic `data broker opt-out procedure` query to Tavily Search. It prints the model response, available token counts, and up to three search result summaries. Do not add family identifiers to this connectivity check.

## Current implementation boundary

This increment runs directly on the host. It is not protected by OpenShell and does not establish the project's egress guarantee. The brief requires OpenShell on Linux; this checkout was prepared on Windows without WSL or Docker, so sandbox enforcement, the boundary test, and Policy Prover evidence remain unimplemented and unverified.

The brief specifies `https://api.tokenfactory.us-central1.nebius.com/v1/`. Nebius's current [official quickstart](https://docs.tokenfactory.nebius.com/quickstart) documents `https://api.tokenfactory.nebius.com/v1/`; the connectivity check uses the documented base URL. Confirm the regional URL with Nebius before adding it to an OpenShell allowlist. The requested model ID comes from the project brief and has not been live-verified in this environment.

No real family or child data belongs in this repository. All removal messages must remain drafts for human review; this prototype does not submit forms or contact brokers.
