---
name: extract_optout_procedure
description: Extract a site's opt-out procedure into structured steps.
version: 1.0.0
metadata:
  hermes:
    tags: [privacy, data-broker, procedure]
    category: privacy
    requires_toolsets: [web]
required_environment_variables:
  - name: TAVILY_API_KEY
    prompt: Tavily API key
    help: Get one at https://app.tavily.com/home
    required_for: Tavily-backed web_search and web_extract
  - name: NEBIUS_API_KEY
    prompt: Nebius Token Factory API key
    help: Get one at https://tokenfactory.nebius.com/
    required_for: Nemotron tier inference
---

# Extract opt-out procedure

Stage 2 of the Haven pipeline. Maps to `extract_optout_procedures()` in
`src/haven/pipeline.py`. Input: a list of `Exposure`. Output: one
`RemovalProcedure` per exposure that has a findable procedure, keyed by
`exposure_id`.

## When to Use

- Stage 1 produced exposures and each one needs a removal path.
- A procedure is stale, wrong, or missing `statutory_deadline_days` and needs
  re-deriving from the site's current opt-out page.
- A site's removal route changed (new form URL, moved to email, now
  postal-only).

Do not use this skill to submit anything. It reads a procedure; it does not
perform it.

## Quick Reference

| Step | Call | Notes |
| --- | --- | --- |
| Find opt-out page | `web_search` (Tavily Search) | query: `"<site> opt-out removal procedure how to remove personal data"`, `max_results=5` |
| Read the page | `web_extract` (Tavily Extract) | first ~3000 chars of `raw_content` |
| Synthesize | Nemotron **super** tier | JSON only, `temperature=0.2`, `max_tokens=1024` |
| Fallback | `_fallback_procedure()` | `method="manual_only"` |

## Procedure

1. For each exposure, take `source_name` as the site name.
2. Tavily Search: `"<site_name> opt-out removal procedure how to remove personal data"`,
   `search_depth="advanced"`, `max_results=5`.
3. If there are no results, emit the fallback procedure (step 6) and continue.
   Do not loop, retry, or broaden into other hosts.
4. Tavily Extract the top result's URL. Prefer `raw_content`; on failure fall
   back to that result's `content` field. Truncate to ~3000 chars.
5. Ask the **super** tier to synthesize the procedure from the page content.
   Require exactly:
   `{"method": "web_form"|"email"|"postal"|"phone"|"manual_only", "action_url": str|null, "required_evidence": [str], "statutory_deadline_days": int|null, "jurisdiction": str|null, "steps": [str]}`.
   Then build `RemovalProcedure` with `exposure_id`, `source_url` = the page you
   actually read, and every field from that JSON.
6. Fallback — `method="manual_only"`, `action_url` = `exposure.source_url`,
   `required_evidence` = `["Government-issued ID (optional)", "Proof of address"]`,
   `statutory_deadline_days=None`, `jurisdiction=None`, and the four generic
   steps in `_fallback_procedure()`. Use this whenever extraction fails or the
   site forbids automated access.
7. Never guess a `statutory_deadline_days` or `jurisdiction`. `null` is the
   correct answer when the page does not state one.

## Tools and Model Tier

| Tool | Use |
| --- | --- |
| Tavily Search (Hermes `web_search`) | locate the opt-out page in step 2 |
| Tavily Extract (Hermes `web_extract`) | read that page in step 4 |
| Token Factory Nemotron, **nano** | short routing calls: pick the best result, decide "is this page the opt-out page or a blog post about it?" |
| Token Factory Nemotron, **super** | the synthesis in step 5 — this is judgement over messy prose |
| `read_file`, `write_file` | persist `RemovalProcedure` records |

Tier choice: **super** for synthesis. The job is to read an inconsistently
written page and decide what the procedure actually is — which fields are
genuinely absent versus merely unstated, which "steps" are boilerplate. That is
judgement, and nano gets it wrong often enough to matter. Use **nano** for the
routing decisions, which are short and mechanical. **Ultra is not needed**:
the input is one page at a time and fits comfortably in a small context.

## Hard Constraints

1. **Never send high-sensitivity identifiers as a search query or as page
   content.** They exist only to match against results already returned.
   `Identifier.sensitivity` is `"low"` or `"high"` in `src/haven/models.py`, and
   the model comment is explicit: `"high" must never leave the sandbox`. The
   step-2 query is site-name-only for exactly this reason — do not "improve" it
   by adding a name, address, or phone number.
2. **Respect robots.txt and site terms.** If a site forbids automated access,
   stop and record a manual procedure instead. A `manual_only` procedure with
   honest steps is a correct outcome, not a failure. Never route around a
   refusal via a cache, mirror, or alternate host.
3. **No credential stuffing, no bypassing logins or paywalls.** Opt-out pages
   that require an account are read as guests or not at all. Never authenticate,
   never guess or reuse credentials, never defeat a paywall, CAPTCHA, or rate
   limit, and never drive an authenticated session to see a page.
4. **Never include children's names or school details in outbound content.**
   Anything leaving the process is outbound — search queries, extraction
   targets, and prompts included. Do not put a child's name or a school
   identifier into a query, and do not carry one into a procedure step.
5. **All outbound removal requests are DRAFTS for human review.** This stage
   records how a removal would be requested. It must never call `action_url`,
   fill a web form, send an email, dial a phone number, or post mail. The agent
   must never auto-submit to a third-party site.

## Pitfalls

- Recording `action_url` from the search result instead of from the page you
  actually read. `source_url` must be what you extracted, so a human can audit
  it.
- Accepting a third-party "how to opt out of X" blog post as X's procedure.
  Prefer the site's own domain; mark `source_url` so the provenance is visible.
- Inventing a `statutory_deadline_days` from general privacy-law knowledge.
  Only record what the page supports.
- Treating a `manual_only` fallback as a failed run. It is the correct result
  when extraction fails or access is forbidden.
- Letting one site's failure abort the batch. Each exposure is independent.

## Verification

- Every `RemovalProcedure` validates against the model, and its `method` is one
  of `web_form`, `email`, `postal`, `phone`, `manual_only`.
- Every procedure's `exposure_id` matches a real `Exposure.id`, and
  `source_url` is a URL you actually fetched.
- Count the `manual_only` results and confirm each one is explained by either a
  missing page or a site that forbids automated access.
- No request was made to any `action_url`; no form, email, or call left the
  process.
