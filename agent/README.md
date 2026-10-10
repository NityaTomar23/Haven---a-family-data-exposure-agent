# agent/

Hermes Agent configuration for Haven.

Hermes is the agent runtime that drives the Haven pipeline; this directory holds
what Hermes needs to run it. It contains no pipeline logic — the implementation
stays in `src/haven/`.

## Contents

| Path | What it is |
| --- | --- |
| `hermes.env.example` | The environment file Hermes reads. Copy it to `$HERMES_HOME/.env`. |
| `skills/discover_exposure/SKILL.md` | Stage 1 skill. |
| `skills/extract_optout_procedure/SKILL.md` | Stage 2 skill. |
| `skills/draft_removal_request/SKILL.md` | Stage 3 skill. |

## Mapping onto the pipeline

One skill per stage in `src/haven/pipeline.py`. Each skill names its stage's
entry function, so the agent's procedure and the code cannot drift apart
silently.

| Stage | Pipeline function | Skill | Model tier |
| --- | --- | --- | --- |
| 1. Discover exposures | `discover_exposures()` | `discover_exposure` | nano (super to escalate one contested case) |
| 2. Extract opt-out procedures | `extract_optout_procedures()` | `extract_optout_procedure` | nano to route, super to synthesize |
| 3. Draft removal requests | `draft_removal_requests()` | `draft_removal_request` | super per draft, ultra only for strategy at 5+ sites |

Tier ids come from `TIER_MODELS` in `src/haven/llm.py` and are routed to Nebius
Token Factory. Hermes runs one main model per session, so set the tier per stage
via `HERMES_INFERENCE_MODEL`, `-m`/`--model`, or `model.default` in `config.yaml`
— there is no per-call tier switch. The pipeline's per-tier overrides
(`NEBIUS_MODEL_NANO`, `NEBIUS_MODEL_SUPER`, `NEBIUS_MODEL_ULTRA`) are read by
`llm.model_for()` and are Haven application variables, not Hermes variables.

Third stage in, nothing else: the JSON contracts, thresholds, and fallbacks are
in `pipeline.py`; each skill restates them so the agent follows the same shapes
the dashboard consumes (`src/haven/models.py`).

## Setup

1. Copy the environment file:

   ```sh
   cp agent/hermes.env.example "$HERMES_HOME/.env"
   ```

   `HERMES_HOME` defaults to `~/.hermes` on POSIX and `%LOCALAPPDATA%\hermes` on
   Windows.

2. Fill in `NEBIUS_API_KEY` and `TAVILY_API_KEY`. Never commit a real key.

3. Pin the provider in `$HERMES_HOME/config.yaml`. `model.provider` is the
   documented source of truth and the reason `hermes.env.example` does not set a
   provider variable:

   ```yaml
   model:
     provider: "nebius-token-factory"   # alias: nebius
     default: "nvidia/nemotron-3-super-120b-a12b"
   ```

   Or per run: `hermes chat --provider nebius --model <tier model id>`.

4. Make the skills visible to Hermes. Either copy them into the profile:

   ```sh
   cp -r agent/skills/* "$HERMES_HOME/skills/"
   ```

   or point Hermes at this directory in `$HERMES_HOME/config.yaml`:

   ```yaml
   skills:
     external_dirs:
       - <absolute path to haven/agent/skills>
   ```

   External skill directories are writable by the Hermes process when the agent
   uses `skill_manage`, so point at a checkout, not a location you need to keep
   pristine.

5. Verify: `hermes skills list` should show the three skills, and
   `hermes chat -q "show me the discover_exposure skill"` should load one.

## Inference endpoint

All inference goes to **Nebius Token Factory**. The hackathon rules forbid
`integrate.api.nvidia.com` and `build.nvidia.com` as the shipped inference
endpoint, so `NVIDIA_API_KEY` must not be set and `NVIDIA_BASE_URL` must never
point at either host. `hermes.env.example` carries the full warning, and
`src/haven/llm.py` encodes the same rule as `FORBIDDEN_INFERENCE_HOSTS`.

Tavily provides search and extraction, surfaced to Hermes as the `web_search`
and `web_extract` tools.

## Human-in-the-loop rule

This is the project's central safety property, not a preference.

**The agent drafts removal requests. A human reviews and sends them. The agent
must NEVER auto-submit to third-party sites.**

Concretely, for every outbound removal request:

- The agent may produce a draft and mark it clearly as a draft for human review.
- The agent may not call an `action_url`, fill or post a web form, send an email,
  place a call, or generate mail for dispatch.
- The agent may not move an action past `drafted`. `approve_action()` and
  `mark_sent()` are human transitions, and `mark_sent()` refuses anything that
  is not already `approved`.
- If asked to send, approve, or submit, the agent refuses and returns the draft
  for review.

Supporting rules, enforced in every skill: high-sensitivity identifiers (per
`Identifier.sensitivity` in `src/haven/models.py`) never leave the sandbox and
are used only to match returned results; robots.txt and site terms are
respected, and a site that forbids automated access gets a `manual_only`
procedure instead; no credential stuffing and no bypassing logins or paywalls;
no children's names or school details in any outbound content.
