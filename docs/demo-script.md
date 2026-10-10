# Haven — 3-minute demo video outline

Total duration: 180 s. Nine beats. Every beat has a **Say this** line (the words
to speak) and a **Show this** line (what is on screen). Beat 2 also has a
**Disclosure line** that must be spoken; it is not optional.

Reading budget: the spoken lines total roughly 470 words. Read at a normal
155–165 wpm presentation pace, that lands on the beat timings below; at 150 wpm
it runs about 3:08. If you read slower, cut from beats marked `[demo]`. Never
cut the disclosure beats: 2, 6 and 9.

---

## What this repository can and cannot demonstrate today

Read this before recording. It determines what the video is allowed to show.

| Fact | Status |
|---|---|
| Host-side pipeline (`discover → extract → draft → track`), dashboard, evidence parser | Implemented; exercised by the test suite |
| End-to-end run against the live Nebius Token Factory | **Not performed.** No API key in this environment |
| End-to-end run against the live Tavily Search / Extract | **Not performed.** No API key in this environment |
| NVIDIA OpenShell sandbox execution | **Not performed.** Requires Linux with Landlock ABI v3 (Linux 6.2+) and a running Docker daemon (official support matrix: Docker 28.0 minimum; Windows WSL 2 + Docker Desktop is supported but **Experimental**). Source: <https://docs.nvidia.com/openshell/latest/about/support-matrix> |
| `policy/` policy files and `policy/boundary_test.sh` | **Authored but never executed.** The files exist; the Policy Prover and the boundary test have not been run on any host, so no blocking has been observed |
| Real personal data | **None anywhere.** `src/haven/seed.py` is the only data source |

The consequence for the demo: everything about *enforcement* is disclosed on
screen as specified-but-unverified. Do not narrate it as working software.

Beat tags: **[demo]** = visible in a host-only recording; **[prepared]** =
requires the Linux + Docker run and is not yet evidence.

---

## Beat 1 — 0:00–0:20 · The problem

**Say this:** "Data brokers publish a family's address, phone numbers, and, for
children, school and activity details. Opt-out procedures are scattered across
hundreds of sites, each one different."

**Show this:** the dashboard at `http://127.0.0.1:8000/`, top to bottom. Hold on
the **Synthetic Family** panel: parent cards with phone, email and address
rendered as `[REDACTED — high sensitivity]`, child cards showing exactly one
low-sensitivity name field next to redacted `school` identifiers. [demo]

---

## Beat 2 — 0:20–0:40 · The constraint, and how it is enforced

**Say this:** "So the non-negotiable constraint: the agent must reach the public
web while being provably unable to exfiltrate the family's own data. Enforced as
runtime policy, not as a prompt. The evidence comes from the layer doing the
enforcing, never from the agent's own report."

**Disclosure line — say this too:** "This recording is Windows 11 with no WSL and
no Docker. OpenShell has not been executed here. The policy and the boundary test
are authored, not run."

**Show this:** the architecture diagram (or `docs/architecture.md` open at
"Request path and enforcement points"). Point at the boundary between the sandbox
and the network, then at the arrow from the OpenShell audit layer into the
host-side evidence service. Display the status table above while speaking the
disclosure line. [prepared]

---

## Beat 3 — 0:40–1:00 · Discovery

**Say this:** "Discovery: Tavily Search returns candidate listings, and the Nano
tier classifies each one — relevance, broker type, confidence. Only
low-sensitivity identifiers become queries: names, an alias, city and state.
Phone numbers, emails, the street address and both children's schools never
reach the search path. High-sensitivity values match results; they never build a
query."

**Show this:** click **Scan for Exposure**. Cut to the **Exposure Board**: the
table of findings with site, broker type, confidence bar and percentage, the
evidence snippet, and the source link. Zoom one row. [demo]

---

## Beat 4 — 1:00–1:20 · Procedure extraction

**Say this:** "Each site removes data differently. So per finding, the agent
searches for that site's opt-out procedure, reads the page with Tavily Extract,
and has the Super tier return structure rather than prose: method, action URL,
required evidence, deadline, jurisdiction, steps. If extraction fails it records
a manual procedure rather than inventing one."

**Show this:** the **Removal Actions** panel, specifically the meta line under
each action header: `Method: web form · Model: nemotron-3-super-120b-a12b`.
Show one card with a populated `action_url` if the run produced one. [demo]

---

## Beat 5 — 1:20–1:40 · Draft, and the approval gate

**Say this:** "Each procedure becomes a per-site action card with a drafted
removal request, without children's names, with placeholders for the human's own
contact details. Nothing is submitted automatically. The status machine is
strict — drafted, approved, sent, confirmed removed — and each transition is
refused unless the previous one happened. The agent drafts. A person sends."

**Show this:** one action card: the `drafted` status badge, the draft text, then
click **Approve**, then **Mark as Sent**, then **Confirm Removed**. After each
click the card's badge changes and the summary cards at the top of the page
update. [demo]

---

## Beat 6 — 1:40–2:00 · The outcome count

**Say this:** "That gives four numbers across the top: N listings found, M
requests sent, K confirmed removed, J pending. I will read the numbers the screen
is actually showing. A removal counts as confirmed only when a human presses
Confirm Removed — the agent never marks its own work complete."

**Show this:** the four summary cards, left to right: **Exposures Found**,
**Requests Sent**, **Confirmed Removed**, **Pending**. Read the actual integers
off the screen. [demo]

**Validity condition:** if the recording is made with no live Tavily or Nebius
key, the run produced nothing, the cards read `0`, and the Exposure Board and
Removal Actions panels show their empty states. Either record this beat against a
run made with keys available, or say plainly that the counts are zero because no
provider keys are present in the recording environment. Do not substitute a
number or a screenshot from another run.

---

## Beat 7 — 2:00–2:20 · Model tiering

**Say this:** "Every model call goes to Token Factory, routed by tier, and logged
with its tokens and latency. Nano does the every-result work: classifying and
routing. Super reasons and writes: procedures, single-site drafts. Ultra is
reserved for multi-site strategy, at five or more sites. Here is the measured
split."

**Show this:** the **Model Tier Usage** chart. Per tier: model id, call count,
input tokens, output tokens, and average latency, with the relative token bar.
Read the actual per-tier values and their latencies off the screen. [demo with
keys; the chart is empty without them]

---

## Beat 8 — 2:20–2:40 · The boundary panel

**Say this:** "This panel answers one question: what actually left this machine?
The source label says it — OpenShell OCSF audit logs, from the enforcement layer,
not from the agent. The agent cannot write or suppress these records. Per
destination: allowed and denied counts, and the policy that matched. With no
audit log the reader returns nothing rather than inventing an entry."

**Show this:** scroll to **Data That Left This Machine**. Show the source line
verbatim, the allowed/denied totals, and the per-destination cards with their
policy names. Then disclose the state on screen: on this host the log path does
not exist, so the panel is in its empty state, and no record shown here was
produced by an enforcing sandbox. [demo, with disclosure; the populated panel is
prepared, not yet observed]

---

## Beat 9 — 2:40–3:00 · Close

**Say this:** "So: enforced, or claimed. Enforced in code, with tests:
high-sensitivity identifiers never build an outbound request; the evidence reader
never fabricates an allowed record; nothing reaches sent without human approval.
Claimed: the sandbox boundary. The policy and the boundary test are authored, and
neither has been run. Until then the boundary is designed, not demonstrated."

**Show this:** the two-column claims table in `docs/architecture.md` under
**"What is enforced vs what is claimed"**. Hold on it. End on the repository URL.
[prepared]

---

## Pre-recording checklist

1. `uv sync` on a clean checkout.
2. Copy `.env.example` to `.env` and set `NEBIUS_API_KEY` and `TAVILY_API_KEY`.
   Without these, beats 3–7 render empty states.
3. `uv run pytest` — the suite must be green before recording. A failing test
   narrated as passing invalidates the recording.
4. `uv run python scripts/serve.py` — binds `127.0.0.1:8000` by default
   (`HAVEN_HOST`, `HAVEN_PORT` override).
5. Record at 1400 px wide or narrower so the summary grid and the evidence grid
   do not reflow mid-shot.
6. If OpenShell has been brought up: set `HAVEN_AUDIT_LOG` to the sandbox's OCSF
   egress log path and populate beat 8 from it. Drop the "not yet run"
   disclosure in beats 2 and 9 **only** if the boundary test and the Policy
   Prover actually ran and their output is saved in `docs/`.

---

## Claims boundary for this video

Elaboration of beat 9; use it to vet every sentence before publishing.

**Safe to assert (mechanisms in this repository, exercised by tests today):**

- High-sensitivity identifiers are withheld from search queries by code in
  `src/haven/seed.py` and `src/haven/pipeline.py`; outbound payload content is
  asserted by `tests/test_privacy_invariants.py`.
- The dashboard states that the evidence panel's source is the enforcement layer
  and not the agent.
- The evidence reader parses OCSF records and refuses to synthesize an `allowed`
  decision it did not read.
- Status transitions are ordered and human-gated: drafted → approved → sent →
  confirmed removed.
- All demo data is synthetic; `src/haven/seed.py` is the only data source.
- Tiering is routing code with per-tier token and latency logging.

**Scoped to outbound content only.** "No child data leaves the machine" is true
of what the pipeline sends, not of what the dashboard displays locally: the
family panel renders each child's name in its card heading while redacting the
`school` identifier beside it. `tests/test_privacy_invariants.py` records that as
a known gap with an `xfail`, so do not claim the display is redacted too.

**Not safe to assert without the Linux + Docker run:**

- "The boundary test passes." It has not been run.
- "Every host except the allowlisted ones gets a 403." That is the intent of the
  authored policy, not an observed result.
- "The Policy Prover proved the boundary." No Prover output exists.
- "The agent cannot leak the family's data." The supported claim is narrower: no
  leak was found in the code paths that were tested, on a host with no sandbox.
- "The agent never holds the API keys." Credential brokering at the proxy
  boundary is the intended OpenShell design. In the current host-only code,
  `src/haven/llm.py` and `src/haven/research.py` read the keys from process
  environment variables.
