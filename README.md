# Haven — Family Data-Exposure Agent

**Privacy-preserving personal-data discovery, opt-out procedure research, and human-gated removal drafting on Nebius Token Factory, Tavily, and NVIDIA OpenShell.**

> **Built for the Nebius × NVIDIA Global AI Hackathon (2026) — MIT Licensed ([`LICENSE`](LICENSE)).**

---

## Core Privacy Guarantee

Haven is built around a simple premise: **a privacy agent must never leak personal data to discover or remove personal data.**

1. **Zero-PII External Research:** Haven never queries Tavily Search, Tavily Extract, or any LLM with a person's name, email, phone number, address, or listing URL.
2. **Fail-Closed Outbound Gate ([`src/haven/privacy.py`](src/haven/privacy.py)):** Every outbound request body passes through `haven.privacy.check()` *before* the Tavily or OpenAI SDK client is even constructed. Any payload containing a protected family identifier, surname, phone digit sequence, email/local part, address, city/state, listing URL, or raw listing sentence raises `PayloadBlocked` and refuses to send.
3. **Purely Local Matching ([`src/haven/fixtures.py`](src/haven/fixtures.py)):** Profile matching runs 100% locally against synthetic RFC 2606 `.example` listing fixtures using exact identifier rules (`verified`, `candidate`, `rejected`) — never an LLM relevance score.
4. **Placeholder-Only Drafting & Human Gates ([`src/haven/pipeline.py`](src/haven/pipeline.py), [`src/haven/api.py`](src/haven/api.py)):** Drafts use placeholders (`[FULL_NAME]`, `[LISTING_URL]`, `[EMAIL]`, `[PHONE]`, `[ADDRESS]`). Haven has no email sender or form submitter and strictly enforces `drafted → approved → sent → confirmed_removed`.
5. **Pre-Scan Consent & Rate Limiting:** `POST /api/scan` requires explicit `{"consent": true}` (rejecting any extra personal-data fields with `422`) and enforces a sliding-window hourly rate limit (`HAVEN_SCAN_RATE_LIMIT`, default `10/hr`).

> [!WARNING]
> **Sanctioned Endpoints Only:** All LLM inference routes strictly to **Nebius Token Factory** (`https://api.tokenfactory.us-central1.nebius.com/v1/` by default, or `https://api.tokenfactory.nebius.com/v1/` via `NEBIUS_BASE_URL`). Never route inference to `integrate.api.nvidia.com` or `build.nvidia.com` — both are explicitly denylisted in `llm.FORBIDDEN_INFERENCE_HOSTS` and excluded from `policy/policy.yaml`.

---

## Architecture & Tiered NVIDIA Nemotron 3 Stack

| Stage | Network | Model / Tool | Output & Guardrail |
|---|---|---|---|
| **0. Seed Family** | None (local) | `haven.seed` | Deterministic adults-only synthetic household (`Avery Synthwell` & `Jordan Synthwell`, `Sampleville, CA 00000`, `@example.com`, `555-01xx`) |
| **1a. Generic Inventory** | External (PII-free) | Tavily Search + **Nemotron 3 Nano** | Classifies data-broker sites from generic category queries; tags `local_fixture` vs `manual_only` |
| **1b. Local Matching** | None (local) | `haven.pipeline.match_local_listings` | Exact local match against 7 `.example` listings → `verified`, `candidate`, or `rejected` (high-sensitivity values redacted in snippets) |
| **2. Procedure Research** | External (PII-free) | Tavily Search/Extract + **Nemotron 3 Super** | Fences retrieved web pages inside `<untrusted_page_content>` tags; records `statutory_deadline_days` only when both `jurisdiction` and an authoritative `deadline_source_url` are verified (distinct from `service_target_days`) |
| **3a. Multi-Site Strategy** | External (PII-free) | **Nemotron 3 Ultra** | Synthesizes a cross-broker removal sequence when 5+ non-rejected exposures exist |
| **3b. Request Drafting** | External (PII-free) | **Nemotron 3 Super** | Produces placeholder-only drafts for human review (`[FULL_NAME]`, `[LISTING_URL]`, etc.) |
| **4. Egress Evidence** | Host / Local | `haven.evidence` | Parses OpenShell OCSF JSONL logs (`evidence_status`: `real`, `simulated`, or `unavailable`) without fabricating missing fields |

---

## Quick Start

### 1. Local Python (One-Command Launch)

```bash
cp .env.example .env
# Add NEBIUS_API_KEY and TAVILY_API_KEY for live inference,
# or leave HAVEN_PROVIDER_MODE=auto to run in labeled offline/simulated mode.

# Option A: uv
uv sync
uv run python scripts/serve.py

# Option B: standard Python / bash helper
pip install -e .  # or install dependencies from pyproject.toml
bash scripts/run_demo.sh
```

Open **http://127.0.0.1:8000** in your browser, check the explicit pre-scan consent box, and click **Run Privacy Scan**.

### 2. Docker

```bash
docker build -t haven .
docker run --rm -p 8000:8000 --env-file .env haven
```

### 3. Provider Modes (`HAVEN_PROVIDER_MODE`)

* `auto` *(default)*: Uses live Nebius Token Factory + Tavily when both `NEBIUS_API_KEY` and `TAVILY_API_KEY` are set; otherwise falls back cleanly to deterministic local stand-ins (`haven.offline`) and labels every tier usage entry and simulated OCSF record as **simulated**.
* `live`: Requires both keys and fails loudly instead of falling back.
* `offline`: Runs completely offline (`simulated=True`), useful for UI walkthroughs without spending credits.

---

## Testing & Repository Guardrails

Run the full automated suite (`229` tests covering privacy invariants, local matching, consent/rate gates, OCSF log parsing, YAML sandbox policies, and compliance guardrails):

```bash
python -m pytest tests/ -v
```

Once you have a `NEBIUS_API_KEY` and `TAVILY_API_KEY`, verify live Token Factory models and run the end-to-end compliance spine:

```bash
python scripts/verify_models.py
python scripts/compliance_spine.py
```

---

## Verification Status — Honest Disclosure of What Has & Has Not Been Run

To uphold strict hackathon engineering integrity, here is the exact verification boundary of this repository:

* **Verified locally:**
  * All **229 pytest checks** pass (privacy canary gate failing closed before SDK calls, zero-PII outbound payload checks across the pipeline, local `verified`/`candidate`/`rejected` matching, strict statutory deadline provenance, explicit `/api/scan` consent & rate limiting, OCSF evidence parsing & status classification, policy YAML schema validation, and executable compliance guardrails).
* **Not yet verified in this build environment:**
  1. **NVIDIA OpenShell Runtime & Policy Prover:** `policy/policy.yaml`, `policy/policy.hardened.yaml`, and `policy/boundary_test.sh` were statically validated against schema invariants in `tests/test_boundary.py`, **not** executed under `openshell sandbox create` (the workspace host ran Windows 11 without WSL2/Docker or Linux Landlock ABI v3+). Supervisor-grade OCSF egress enforcement must be verified on Linux/OpenShell (`policy/README.md`).
  2. **Live Nebius Token Factory & Tavily Calls (`nano` model ID):** Live API keys were not present in the build environment. While `nvidia/nemotron-3-super-120b-a12b` and `nvidia/Nemotron-3-Ultra-550b-a55b` match the Nebius cookbook, the default `nano` ID (`nvidia/nemotron-3-nano-30b`, candidate `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`) remains **unverified** against `/v1/models` until `python scripts/verify_models.py` is run with a live `NEBIUS_API_KEY` (override via `NEBIUS_MODEL_NANO`).

---

## Project Layout

```text
src/haven/
  api.py        FastAPI app, consent/rate-limit gates, human action transitions, dashboard
  evidence.py   OpenShell OCSF JSONL parser & real/simulated/unavailable status classifier
  fixtures.py   7 synthetic RFC 2606 .example listings (verified, candidate, rejected, none)
  llm.py        Nebius Token Factory client (nano/super/ultra) + forbidden host denylist
  models.py     Pydantic domain models (adults-only household, match_status, provenance)
  offline.py    Deterministic simulated Tavily/OpenAI stand-ins for keyless demo runs
  pipeline.py   Discover inventory -> local match -> opt-out extract -> strategy -> draft
  privacy.py    Fail-closed outbound payload gate blocking family & listing terms pre-SDK
  research.py   Identifier-free Tavily Search & Extract wrappers
  seed.py       Deterministic adults-only Synthwell household generator & redactor
policy/         OpenShell Landlock + network egress YAML policies & boundary test script
agent/          Hermes-style skill specifications & memory policy
web/templates/  Server-rendered dark-mode operational privacy dashboard
scripts/        serve.py, compliance_spine.py, verify_models.py, run_demo.sh
tests/          229 automated unit, integration, boundary, and guardrail checks
```
