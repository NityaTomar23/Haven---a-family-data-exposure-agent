# Haven

**A family data-exposure agent that finds where a family's personal information
is publicly exposed, and drives the removal.**

> It's a smoke detector for your family's data — and it proves it can't leak the
> very data it protects.

## The problem

Data brokers, people-search sites, and breach dumps expose a family's home
address, phone numbers, and — for children — school and activity details.
Opt-out procedures are scattered across hundreds of sites, each with a different
process. Parents do not have forty hours to chase them.

Haven researches which brokers plausibly hold records, extracts each site's
opt-out procedure, drafts a removal request per site, and tracks every request
to completion on a dashboard.

## The non-negotiable design constraint

**The agent must be able to reach the public web to find exposed data, while
being provably incapable of exfiltrating the family's own personal data.**

That has to be enforced by the sandbox runtime as code, not by a prompt, and the
evidence of enforcement has to be captured by the enforcement layer rather than
self-reported by the agent. A demo where the agent displays a privacy counter it
controls proves nothing.

## Status — read this before believing anything else

This repository is honest about the difference between what is implemented and
what is proven. **No claim in this README about the sandbox boundary has been
executed.**

| Claim | Status |
| --- | --- |
| Discovery → procedure extraction → drafting → tracking pipeline | **Implemented**, exercised by the test suite |
| Dashboard with exposure board, action tracker, tier-usage chart, egress panel | **Implemented**, renders under test |
| Evidence reader parses OpenShell OCSF audit logs | **Implemented**, asserted against the published OCSF v1.8.0 record shapes |
| OpenShell sandbox blocks non-allowlisted egress with a 403 | **Authored, UNVERIFIED.** The policy and boundary test exist and have never been loaded or run |
| OpenShell Policy Prover has proven the boundary | **Not run.** No Prover output exists in this repository |
| The agent process never holds the Tavily or Nebius keys | **Design intent only.** With no sandbox in place, `llm.py` and `research.py` read the keys from the environment |
| End-to-end run against live Token Factory / Tavily | **Not performed.** No API key was available in this environment |
| Real personal data | **None anywhere.** `src/haven/seed.py` generates a synthetic family and is the only data source |

The sandbox half could not be built here: OpenShell requires Linux with
[Landlock](https://docs.kernel.org/security/landlock.html) ABI v3 (Linux 6.2+)
plus a Docker daemon (official minimum 28.0), and this checkout was prepared on
Windows 11 with neither WSL nor Docker installed. See
[docs/architecture.png](docs/architecture.png) for the diagram,
[docs/architecture.md](docs/architecture.md) for the full "what is enforced vs
what is claimed" breakdown, and [policy/README.md](policy/README.md) for what
still needs to be verified on a Linux host.

## Quickstart

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <your-fork> haven && cd haven
cp .env.example .env          # then add your two API keys
uv sync
```

Check that every configured model id actually exists on the endpoint. This is
the only way to settle the nano tier, whose id is **unverified** (see
[Model tiering](#model-tiering)):

```bash
uv run python scripts/verify_models.py --list
```

Run the tests — no API keys needed, and no test touches the network:

```bash
uv run pytest
```

Run the dashboard:

```bash
uv run python scripts/serve.py     # http://127.0.0.1:8000
```

`uvicorn haven.api:app` on its own raises `ModuleNotFoundError`: the project sets
`[tool.uv] package = false`, so `haven` is never installed and `scripts/serve.py`
puts `src/` on the import path instead.

Finally, the day-one compliance spine, which sends one fixed, generic prompt and
one generic search and accepts no family identifiers:

```bash
uv run python scripts/compliance_spine.py
```

## How Token Factory is used

Every model call goes to Nebius Token Factory over the OpenAI-compatible API. No
other inference endpoint is permitted in shipped code, and a test enforces that
(see [Guardrails](#guardrails)).

| Tier | Role | Model | Verified? |
| --- | --- | --- | --- |
| nano | extraction, classification, routing — every-turn calls | `nvidia/nemotron-3-nano-30b` | **No** — see below |
| super | the workhorse: reasoning, drafting, planning | `nvidia/nemotron-3-super-120b-a12b` | Yes |
| ultra | hard cases only: multi-site strategy over long context | `nvidia/Nemotron-3-Ultra-550b-a55b` | Yes |

*Verified* means the exact id appears in Nebius's official
[Token Factory cookbook](https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/README.md).
The nano id does **not** appear there. The 30B-class Nemotron listed is
`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, and the featured small model is
`nvidia/Nemotron-3_5-Lightning`. Run `scripts/verify_models.py` against a live
key to settle it, then set `NEBIUS_MODEL_NANO`.

Per-tier token counts and latency are logged and rendered as a chart, so the
tiering can be shown to pay off rather than merely asserted.

### Endpoint

The default is the region-specific host the project brief mandates,
`https://api.tokenfactory.us-central1.nebius.com/v1/`. Nebius documents public
endpoints as global and warns that a region-specific base URL *"can stop working
if the endpoint's processing region changes"*. The documented region-free host is
`https://api.tokenfactory.nebius.com/v1/`, and setting `NEBIUS_BASE_URL` switches
to it. Both hosts are allowlisted in `policy/policy.yaml`, so switching is a
configuration change rather than a policy change.

## How Tavily is used

Tavily is the agent's research mechanism, not a decoration:

* **Tavily Search** (`search_depth="advanced"`) finds candidate broker and
  people-search listings, then finds each site's opt-out procedure page.
* **Tavily Extract** reads those pages so the procedure can be synthesized.

`src/haven/research.py` wraps both. The installed SDK (0.8.5) also exposes
`crawl`, `map`, and an `AsyncTavilyClient`, but **no `research` method** — that
endpoint is not available in the pinned version.

## Security model

The intended deployment puts the agent inside an OpenShell sandbox with a
deny-by-default policy:

* **Only two hosts are reachable** — Token Factory and Tavily — and only for the
  specific REST methods and paths the agent needs. Everything else returns 403.
* **Credentials are brokered at the proxy boundary**, so the agent process never
  holds the API keys.
* **Filesystem access is restricted** to the sandbox working directory and
  `/tmp`; the rest of the filesystem is read-only or absent.
* **`landlock.compatibility: hard_requirement`**, not `best_effort`. The latter
  silently runs *without* the filesystem rules when they cannot be applied, which
  would void half the policy. The Policy Prover agrees: it reports
  `exceeds_boundary` when a candidate downgrades to `best_effort`.
* **Evidence comes from the enforcement layer.** The dashboard's "what left this
  machine" panel reads OpenShell's OCSF audit JSONL and is labelled on screen as
  coming from OpenShell rather than from the agent.

A second, stronger control is authored but *not* prover-verifiable:
`policy/policy.hardened.yaml` adds an `openshell/regex` middleware that redacts
high-sensitivity patterns from allowed request bodies, failing closed. The Prover
models only filesystem, process, Landlock, L4, and REST, so a policy using
`network_middlewares` may return `unsupported` — which counts as a failure. The
arrangement is therefore: **run** the hardened policy, **prove** the core one.
See [policy/README.md](policy/README.md).

### What would prove it

```bash
policy/boundary_test.sh haven
```

Four steps: an allowlisted host must be reachable (a positive control, so a
totally broken network cannot make the negative test pass vacuously); a
non-allowlisted host must fail *through an allowlisted binary*, so the failure is
a policy denial rather than a missing executable; the Prover must report
`within_boundary` for `policy.yaml`; and it must report `exceeds_boundary` for
`policy/counterexample.yaml`, which proves the Prover actually discriminates.
Only `within_boundary` is a pass.

**None of this has been run.** The script's output belongs in `docs/`.

## Guardrails

Hackathon compliance constraints, enforced as tests rather than promises:

* no shipped code or configuration routes to `integrate.api.nvidia.com` or
  `build.nvidia.com` — **these must never be the inference endpoint**; the only
  permitted mention is the denylist constant in `llm.py`, and the prose is
  required to warn about them;
* all three tiers are distinct NVIDIA open models;
* shipped modules may not import a raw HTTP client (`requests`, `httpx`,
  `aiohttp`, `urllib`, `smtplib`, `selenium`, `playwright`) — only the Tavily and
  OpenAI SDKs may reach the network, which is what makes "no automated form
  submission" checkable;
* the README must disclose the unverified sandbox status. A README that implies
  a proof that was never run fails the suite.

## Privacy invariants

`tests/test_privacy_invariants.py` drives a full pipeline run with fakes on both
providers, records every payload that *would* have crossed the network boundary,
and asserts no high-sensitivity identifier value is in any of them. Additional
guards: no search query may contain a digit or `@` (every identifier with either
is high-sensitivity); the classifier prompt must show `[REDACTED]` in place of
high-sensitivity values; and no child name or school may appear in an outbound
draft prompt.

Two display behaviours are deliberate and pinned by tests, so neither can drift
silently:

1. **The dashboard family card shows member names** — including a child's. The
   local operator console is not an egress path, and the parent already knows
   their own child's name. What must not follow the name is the sensitive
   context around it, which is why the school identifier is redacted directly
   beside it.
2. **`GET /api/family` redacts high-sensitivity identifier values by default.**
   The API must not hand out what the UI it feeds refuses to display, and the
   hackathon requires a public hosted demo URL. `?reveal=true` is the explicit
   local-operator opt-in for the raw values.

Neither behaviour weakens the actual invariant, which is about egress: the
dashboard can print a name, but no high-sensitivity value may appear in any
payload sent to a model or a search API.

## Consent and ethics constraints

* The demo uses **synthetic personas only**. `seed.py` is the only data source.
* **No automated form submission.** The agent drafts; a human reviews and sends.
  `mark_sent` refuses any action that has not already been approved.
* **No credential stuffing, no bypassing logins or paywalls, no scraping behind
  authentication.**
* Obey `robots.txt` and each site's terms. If a site forbids automated access,
  record the manual procedure for the parent instead of attempting access.
* Human-in-the-loop on all outbound content.

## Repository layout

```
haven/
├── LICENSE                  MIT
├── agent/                   Hermes env template, the three pipeline skills, memory note
├── docs/                    architecture (md + png), 3-minute demo script
├── policy/                  OpenShell policy, boundary policy, counterexample, boundary test
├── scripts/                 compliance spine, model verification, serve
├── src/haven/
│   ├── llm.py               tiered Nemotron client + per-tier usage logging
│   ├── research.py          Tavily Search / Extract wrappers
│   ├── models.py            pydantic models
│   ├── pipeline.py          discover → extract → draft → track
│   ├── evidence.py          host-side reader for OpenShell OCSF audit logs
│   ├── api.py               FastAPI JSON API + dashboard
│   └── seed.py              synthetic family generator
├── tests/                   275 tests
└── web/templates/           dashboard
```

The diagram is generated, not hand-drawn: `python docs/make_architecture_diagram.py`
rewrites `docs/architecture.png`, so it can be regenerated when the architecture
changes. Test modules are named for what they cover — `test_boundary.py` holds
the boundary-artifact assertions, `test_pipeline.py` the end-to-end run, and the
per-stage behaviour lives in `test_pipeline_discovery.py`,
`test_pipeline_procedures.py`, `test_pipeline_transitions.py` and
`test_pipeline_json.py`.

## Licence

MIT — see [LICENSE](LICENSE).
