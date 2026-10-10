# Haven — architecture

Haven finds where a family's personal information is publicly exposed on data
brokers and people-search sites, extracts each site's removal procedure, drafts
a removal request for human review, and tracks each request to a confirmed
removal. Its distinguishing property is supposed to be a boundary: the agent
reaches the public web while being incapable of sending the family's own
high-sensitivity identifiers off the machine, with the enforcement performed by
the sandbox runtime and the evidence of that enforcement produced by the runtime
rather than by the agent.

Read the section **"What is enforced vs what is claimed"** before repeating any
statement from this document elsewhere. On the development host (Windows 11, no
WSL, no Docker) the sandbox path has never been executed.

---

## Diagram

Upper half is design: the sandbox path required by the project brief. Lower half
is the host-side code that exists and runs in this checkout today.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ HOST                                                                         │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ NVIDIA OpenShell sandbox — policy-enforced            [design, not run]│  │
│  │                                                                        │  │
│  │   policy/                                                              │  │
│  │     policy.yaml ....... allowlist + default deny. Authored, UNVERIFIED │  │
│  │     boundary_test.sh .. probe for the deny path. Authored, NOT RUN     │  │
│  │                                                                        │  │
│  │   filesystem: Landlock LSM  (Linux; no native Windows/macOS support)   │  │
│  │   network:    default deny; only allowlisted endpoints are reachable   │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │  │
│  │  │ Hermes agent harness                                             │  │  │
│  │  │   skills/  discover · extract opt-out procedure · draft request  │  │  │
│  │  │   memory   snapshot / restore                                    │  │  │
│  │  │   tools ──┬── Tavily Search / Extract   (research)               │  │  │
│  │  │           └── Nebius Token Factory      (nemotron nano/super/ultra)│ │  │
│  │  └──────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────┬────────────────────────────────────────┘  │
│                                  │  request leaves the sandbox               │
│                                  │  carrying NO credential; the agent         │
│                                  │  process never holds the keys              │
│  ┌───────────────────────────────▼────────────────────────────────────────┐  │
│  │ Credential-brokering proxy at the boundary            [design, not run]│  │
│  │   matches destination against the allowlist                            │  │
│  │   injects the Tavily / Nebius credential after the check               │  │
│  │   emits one OCSF egress record per request: time, dst_endpoint,        │  │
│  │   disposition_id (1 = allowed, 2 = denied), matched policy name,       │  │
│  │   bytes_out, request_count                                            │  │
│  │                                                                        │  │
│  │   allowed: api.tokenfactory.nebius.com, api.tavily.com                 │  │
│  │   denied : everything else → 403, surfaced to the agent as a tool error│  │
│  └───────────────────────────────┬────────────────────────────────────────┘  │
│                                  │  OCSF egress log                          │
│                                  │  (default /var/log/openshell/egress.jsonl, │
│                                  │   HAVEN_AUDIT_LOG overrides)              │
│  ┌───────────────────────────────▼────────────────────────────────────────┐  │
│  │ Host-side evidence service      src/haven/evidence.py   [implemented]  │  │
│  │   read_egress_log() ........... parse OCSF lines; skip truncated ones; │  │
│  │                                 never invent an "allowed" it did not   │  │
│  │                                 read; empty list when no log exists    │  │
│  │   _parse_ocsf_record() ........ time|timestamp → ts                    │  │
│  │                                 dst_endpoint.hostname|ip → host        │  │
│  │                                 disposition_id 1 → allowed, else denied│  │
│  │                                 policy.name → matched_policy          │  │
│  │   summarize_egress() .......... allowed/denied counts + bytes per host │  │
│  └───────────────────────────────┬────────────────────────────────────────┘  │
│                                  │                                           │
│  ┌───────────────────────────────▼────────────────────────────────────────┐  │
│  │ Dashboard   FastAPI, web/templates/dashboard.html      [implemented]   │  │
│  │   summary cards ....... N found · M sent · K confirmed · J pending     │  │
│  │   exposure board ...... site, broker type, confidence, snippet, URL    │  │
│  │   action tracker ...... per-site action cards + status transitions     │  │
│  │   boundary panel ...... "Data That Left This Machine": allowed vs      │  │
│  │                         denied per host + the matched policy, labelled │  │
│  │                         on screen as OpenShell OCSF audit logs         │  │
│  │   tier usage chart .... per-tier calls, tokens, average latency        │  │
│  └───────────────────────────────┬────────────────────────────────────────┘  │
│                                  │                                           │
│                          human reads, approves, sends                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

In the rendered dashboard the four panels carry emoji in their headers
(`web/templates/dashboard.html`). They are omitted above because this document
is plain ASCII.

---

## Components

### Host

The host runs the FastAPI application and owns the network boundary. OpenShell
requires Linux with Landlock ABI v3 (Linux 6.2+) available and a running Docker
daemon — the official support matrix lists Docker 28.0 as the minimum and
records Windows WSL 2 + Docker Desktop as supported but Experimental
(<https://docs.nvidia.com/openshell/latest/about/support-matrix>). The
development host for this checkout is
Windows 11 with no WSL and no Docker, so the sandbox half of the diagram has not
been brought up here. `src/haven/seed.py` is the only data source and generates a
synthetic family; there is no real personal data anywhere in the repository.

### NVIDIA OpenShell sandbox (policy-enforced)

OpenShell is the component that is supposed to turn the project's privacy claim
from a promise into a mechanism. Two of its properties matter:

- **Filesystem policy via the Landlock LSM.** Landlock is a Linux kernel feature
  and does not exist natively on Windows or macOS, which is why the sandbox path
  cannot be exercised in this checkout even in principle.
- **Network policy as default-deny.** The intended policy is `policy/policy.yaml`:
  allow the two inference and research endpoints, deny everything else with a
  403, and record each decision. Hermes surfaces a denial to the agent as a tool
  error, so the agent observes a refusal it cannot override.

The status of these artifacts is the thing not to overstate: the policy file and
`policy/boundary_test.sh` are **authored but unverified**, and **the boundary
test has not been run**. Neither has the OpenShell **Policy Prover**, whose
output would be the strongest available evidence of the boundary and which would
belong in this directory. Nothing in the repository currently demonstrates that
a non-allowlisted destination is blocked.

### Hermes agent harness (inside the sandbox)

Hermes is the agent runtime: skills for the three research stages, a
snapshot-able memory directory, and the tool surface (Tavily Search, Tavily
Extract, Token Factory chat completions). All inference is routed to Nebius
Token Factory through an OpenAI-compatible base URL, and the model is selected
by tier:

| Tier | Model | Used for | Where in code |
|---|---|---|---|
| nano | `nvidia/nemotron-3-nano-30b` | classify a search result, route work | `pipeline._classify_result` |
| super | `nvidia/nemotron-3-super-120b-a12b` | synthesize an opt-out procedure; draft a single-site request | `pipeline._extract_single_procedure`, `pipeline._draft_single_request` |
| ultra | `nvidia/Nemotron-3-Ultra-550b-a55b` | multi-site removal strategy when 5+ sites are in play | `pipeline._draft_single_request(use_ultra=True)` |

`src/haven/llm.py` logs input tokens, output tokens and wall-clock latency per
call with its tier and purpose; the dashboard aggregates those records into the
tier-usage chart. This is a routed, measured split in the code — the log is
empty until calls are actually made, and no call has been made against the live
endpoint in this environment.

### Credential brokering at the proxy boundary

The design intent, and one of the project's strongest claims when the sandbox
runs: credentials are injected at the proxy boundary after the destination
check, so the agent process never holds the Tavily or Nebius key. The agent's
request carries no credential; the proxy adds it only for an allowlisted
destination. If that holds, an agent that is compromised or simply misbehaving
has no key in its process memory to send to an arbitrary host. This has not been
observed on this host, so treat it as the intended property of the sandbox run.

**Current state, stated plainly.** This brokering is an OpenShell runtime
property, not something this repository implements. In the host-only code that
exists today, `src/haven/llm.py` and `src/haven/research.py` read `NEBIUS_API_KEY`
and `TAVILY_API_KEY` from process environment variables and pass them to the SDK
clients directly. On a host with no OpenShell, the keys are therefore held by the
agent process. Do not describe the brokering as in force until the sandbox run
has happened.

### Host-side evidence service

`src/haven/evidence.py` is the host-side reader for the enforcement layer's
output. It exists so that the dashboard's most important panel is not sourced
from the agent's own report — a counter the agent controls would prove nothing.

- `read_egress_log(path=None)` reads JSON-lines OCSF records from
  `HAVEN_AUDIT_LOG` (default `/var/log/openshell/egress.jsonl`), skips blank and
  malformed lines, and returns an empty list when the file does not exist. It
  never fabricates an entry.
- `_parse_ocsf_record` accepts both the nested OCSF shape (`time`,
  `dst_endpoint.hostname`, `disposition_id`, `policy.name`, `traffic.bytes_out`)
  and a flat development shape, so the same reader works against real audit
  output and against a fixture.
- `disposition_id == 1` maps to `allowed`; any other disposition maps to
  `denied`. The parser is deliberately asymmetric: the only way to show as
  allowed is to have read a record that says so.
- `summarize_egress` produces allowed/denied counts, bytes out, and the matched
  policy names per destination host.

`write_simulated_log` exists for tests and development only; production records
come from OpenShell. `/api/evidence` returns the reader's output with an
explicit `"source": "enforcement_layer"` label, and the dashboard repeats that
label in the panel header and body.

### Dashboard

FastAPI (`src/haven/api.py`) serves the JSON API and the HTML dashboard
(`web/templates/dashboard.html`). Start it with `uv run python scripts/serve.py`
(module path is set up there because the project is deliberately not installed
as a package); it binds `127.0.0.1:8000` by default.

| Surface | Endpoint | Content |
|---|---|---|
| Summary cards | `/` | exposures found; requests sent (sent + confirmed); confirmed removed; pending (drafted, approved, pending) |
| Exposure board | `/api/exposures` | site, broker type, confidence, evidence snippet, source URL |
| Action tracker | `/api/actions` | per-site action card: method, drafting model, draft text, status |
| Status transitions | `POST /api/actions/{action_id}/approve`, `POST .../sent`, `POST .../confirm` | human-gated; each refuses out-of-order transitions |
| Boundary panel | `/api/evidence` | label + allowed/denied per destination + matched policy |
| Tier usage chart | `/api/tier-usage` | calls, input/output tokens, average latency per tier |

The boundary panel is deliberately labelled on screen: source is OpenShell OCSF
audit logs, from the enforcement layer, not from the agent. When no audit log is
present the panel renders its empty state and says that OpenShell on Linux is
required to see real enforcement data. A host-only recording therefore shows the
empty state, which is the honest outcome and not a bug.

### Request path and enforcement points

```
user → dashboard → POST /api/scan → pipeline.run_pipeline
                                       │
   1. discover_exposures ──────────────┤ low-sensitivity identifiers only, built into
      (Tavily Search + nano classify)  │ the query strings; high-sensitivity values
                                       │ are used to match, never to send
                                       │
   2. extract_optout_procedures ───────┤ Tavily Search → Tavily Extract → super
                                       │ (falls back to manual_only, never invents)
                                       │
   3. draft_removal_requests ──────────┤ super, or ultra when ≥5 exposures;
                                       │ children's names excluded from outbound text
                                       │
   4. RemovalAction status machine ────┤ drafted → approved → sent → confirmed_removed
                                       │ each transition refused unless the previous
                                       │ one happened; the agent never sends
                                       │
   5. evidence.read_egress_log ────────┘ enforcement layer → dashboard panel
```

---

## What is enforced vs what is claimed

The distinction this project is built on is the same distinction this document
has to survive: a mechanism constrains behaviour whether or not anyone trusts
it; a promise only describes intended behaviour. Below, every item is placed on
the correct side.

### Enforced today, by code in this repository

| Property | Mechanism | Where |
|---|---|---|
| High-sensitivity identifiers are never used to build an outbound search query | `get_search_identifiers` filters to low sensitivity before any query is constructed; the pipeline never reaches for the high set on the send path | `src/haven/seed.py`, `src/haven/pipeline.py` |
| Outbound payloads contain no high-sensitivity value | Asserted end to end against every recorded payload the pipeline would have emitted | `tests/test_privacy_invariants.py` |
| Child identifiers do not reach a search query | A test collects child identifier values and checks each recorded query | `tests/test_privacy_invariants.py` |
| The model sees `[REDACTED]` instead of high-sensitivity values | Identifier context is built with high values masked before the prompt is sent | `pipeline._classify_result` |
| Egress evidence is attributed to the enforcement layer, not the agent | On-screen source label; asserted by test | `web/templates/dashboard.html`, `api.get_evidence` |
| The evidence reader cannot fabricate an `allowed` decision | Only `disposition_id == 1` yields allowed; missing log yields nothing | `src/haven/evidence.py` |
| No removal request is sent without a human | Status transitions are ordered and each is refused when out of order | `pipeline.approve_action`, `mark_sent`, `mark_confirmed` |
| All data is synthetic | `seed.py` is the only data source | `src/haven/seed.py` |
| Tiering is measured, not asserted | Per-call tier, token and latency logging feeding a chart | `src/haven/llm.py`, `/api/tier-usage` |

These are code paths with tests. They constrain the host-only program. They do
not, by themselves, constrain a determined process that bypasses the application
— that is what the sandbox is for.

One scope limit on the rows above: the redaction guarantees concern *outbound
content and the model prompt*, not the local display. The dashboard's family
panel redacts high-sensitivity identifier values but still prints each child's
name in the member card heading. `tests/test_privacy_invariants.py` records this
as an `xfail` rather than asserting it passes, and `/api/family` returns
identifier values unredacted for the local demo. Neither is a leak off the
machine; neither should be described as redacted.

### Claimed, specified, or intended — not yet demonstrated

| Claim | Real status |
|---|---|
| The sandbox blocks all non-allowlisted egress with a 403 | Policy authored, UNVERIFIED. The boundary test script has **not been run**; no blocking has been observed |
| `policy/boundary_test.sh` proves the deny path | Authored but **not executed**. It cannot run on this host: OpenShell needs Linux with Landlock ABI v3 (Linux 6.2+), plus Docker (official minimum 28.0), and this host is Windows 11 with no WSL and no Docker |
| The OpenShell Policy Prover has proven the boundary | **Not run.** No Prover output exists in this repository; if it runs, its output belongs in `docs/` |
| The agent process never holds the Tavily or Nebius keys | Design intent of proxy-boundary brokering. **Not in force here**: with no OpenShell, `llm.py` and `research.py` read the keys from the environment |
| Haven works against live providers | **No end-to-end run has been performed.** No API key is available in this environment |
| The published outcome counts (N found, M sent, K removed, J pending) reflect a real broker result | The counts are computed from whatever the run produced. With no keys, the run produces nothing and the counts are 0 |
| Restricting attention to `https://api.tokenfactory.nebius.com/v1/` is the correct Nebius endpoint | The brief names a regional URL; the code uses the URL in Nebius's published quickstart. Confirm before adding a host to any allowlist |

### The honest one-sentence summary

Haven's *outbound content* rules are enforced by code in this repository and
covered by tests; Haven's *network boundary* is specified, authored, and
unverified, and the project's own documents — including the on-screen evidence
panel — are written to say so rather than to imply otherwise.
