---
name: draft_removal_request
description: Draft data removal requests for human review.
version: 1.0.0
metadata:
  hermes:
    tags: [privacy, data-broker, drafting, human-in-the-loop]
    category: privacy
required_environment_variables:
  - name: NEBIUS_API_KEY
    prompt: Nebius Token Factory API key
    help: Get one at https://tokenfactory.nebius.com/
    required_for: Nemotron tier inference
---

# Draft removal request

Stage 3 of the Haven pipeline. Maps to `draft_removal_requests()` in
`src/haven/pipeline.py`. Input: a `Family`, the `Exposure` list, and the
`RemovalProcedure` list. Output: one `RemovalAction` per exposure/procedure
pair, each with `status="drafted"`.

This stage produces **drafts only**. A human reviews and sends. The agent never
submits.

## When to Use

- Stages 1 and 2 produced exposures and procedures, and each pair needs a
  written removal request.
- An existing draft needs revising after a procedure changed (new `action_url`,
  new evidence requirement, new statutory deadline).
- A batch needs a multi-site strategy: which sites to hit first, what to share
  between requests, how to sequence them.

Do not use this skill to send, submit, or file anything. Sending is a separate
human act recorded by `mark_sent()`, which refuses any action that is not
already `approved`.

## Quick Reference

| Step | Call | Notes |
| --- | --- | --- |
| Draft one request | Nemotron **super** tier | `temperature=0.3`, `max_tokens=1500`, one site |
| Multi-site strategy | Nemotron **ultra** tier | only when `len(exposures) >= 5` |
| Record the draft | `RemovalAction` | `status="drafted"`, `drafted_model=TIER_MODELS[tier]` |

Draft must contain: (1) a clear statement that this is a data-removal request,
(2) a reference to applicable law when `jurisdiction` is known, (3) the specific
listing URL to remove, (4) a deadline reference when
`statutory_deadline_days` is set, and (5) `[PHONE]` and `[EMAIL]` placeholders
for the human to fill in.

## Procedure

1. Index procedures by `exposure_id`.
2. Decide the tier: `ultra` when `len(exposures) >= 5`, otherwise `super`.
3. Determine the requestor as a **parent** only — the first member with
   `role == "parent"`, `"<first_name> <last_name>"`, else `"The Data Subject"`.
4. For each exposure with a procedure, draft one request. Give the model the
   site name, listing URL, `procedure.method`, `procedure.steps`,
   `procedure.required_evidence`, `procedure.jurisdiction`, and the requestor
   name. Nothing else.
5. Mark the output as a draft in the body text itself, per the system prompt:
   "clearly mark the output as a draft for human review". A reader who only ever
   sees the draft text must know it is unreviewed.
6. Build `RemovalAction` with `id`, `exposure_id`, the `procedure`, the draft
   text, `status="drafted"`, `drafted_model = llm.TIER_MODELS[tier]`, and
   `created_at` / `updated_at` in UTC.
7. On generation failure, write a placeholder naming the failure and pointing at
   the procedure steps, as `_draft_single_request()` does. Still
   `status="drafted"`.
8. Stop. Do not approve, send, or submit. `approve_action()` and `mark_sent()`
   are human transitions.

## Tools and Model Tier

| Tool | Use |
| --- | --- |
| Token Factory Nemotron, **nano** | classify and route: group sites by `procedure.method`, triage which drafts need the same legal citation, pick which of several candidate requests is the template |
| Token Factory Nemotron, **super** | every individual draft — this is judgement and composition |
| Token Factory Nemotron, **ultra** | multi-site strategy only, when `len(exposures) >= 5` |
| `read_file`, `write_file` | persist `RemovalAction` records |

Tier choice:

- **nano** for classification and routing. Deciding "is this a web_form site or
  an email site, and does it cite CCPA or GDPR?" is a short labelled decision.
  Never draft with nano.
- **super** for drafting. A removal request is consequential outbound writing
  that has to be accurate about law, deadlines, and the specific listing. This
  is the workhorse tier and the pipeline default.
- **ultra** only for multi-site strategy over long context — when there are five
  or more sites and the task is to reason across all of them at once (shared
  legal basis, ordering, what to reuse). Do not reach for ultra to draft a
  single request; that is long-context spend for no gain.

## Hard Constraints

1. **Never send high-sensitivity identifiers as a search query, and never place
   one in a draft.** `Identifier.sensitivity` is `"low"` or `"high"` in
   `src/haven/models.py`, and the model comment is explicit: `"high" must never
   leave the sandbox`. High-sensitivity values are for matching returned results
   only. A draft is outbound content, so no phone number, street address, email
   address, or school name goes in it — that is also why the contact fields are
   `[PHONE]` and `[EMAIL]` placeholders for the human to fill in.
2. **Respect robots.txt and site terms.** If a site forbids automated access,
   do not attempt the request programmatically and do not scrape around the
   refusal. Record a `manual_only` procedure instead and let the draft describe
   the manual path. A draft aimed at a site that refused automated access is a
   draft for a human to send, not a job for the agent.
3. **No credential stuffing, no bypassing logins or paywalls.** Never
   authenticate to a broker, never create or reuse an account to reach a form,
   never defeat a paywall, CAPTCHA, or rate limit, and never drive an
   authenticated session. If a removal route requires a login, the draft tells
   the human so.
4. **Never include children's names or school details in outbound content.**
   Outbound content means every draft and every prompt that produces one. The
   requestor is a parent, and only a parent's name may appear in a draft. No
   child's name, age, school identifier, or school detail — not even as
   evidence that a child is exposed.
5. **All outbound removal requests are DRAFTS for human review. The agent must
   NEVER auto-submit to third-party sites.** No `action_url` is called, no form
   is posted, no email is sent, no call is placed, no mail is generated for
   dispatch. `draft_removal_requests()` creates `status="drafted"` only;
   `approve_action()` and `mark_sent()` exist precisely because a human owns
   those transitions. If asked to send, approve, or submit, refuse and hand the
   draft back for review.

## Pitfalls

- Omitting the "this is a draft" marking so a reviewer cannot tell. The marking
  is a required element, not a flourish.
- Using `family.address`, `city`, `state`, or `zip_code` in a draft because it
  "identifies the subject". It does, and it is high-sensitivity data leaving the
  sandbox.
- Selecting a child as requestor. Filter on `role == "parent"` first.
- Asserting a legal deadline or statute the procedure did not record. Cite only
  `procedure.jurisdiction` and `procedure.statutory_deadline_days`, and say the
  deadline is unstated when those are `null`.
- Jumping to `ultra` for a two-site batch. Check the count first; `super` is
  correct below five sites.
- Treating a returned `action_url` as something to call. It belongs in the draft
  text as the place a human goes.

## Verification

- Every `RemovalAction` has `status == "drafted"` and a `drafted_model` naming
  the tier that produced it.
- Grep every draft for `high`-sensitivity values and for any child name or
  school detail. Both must be absent, along with any real phone number or email
  address.
- Each draft visibly states that it is a draft for human review, includes the
  listing URL, and includes the `[PHONE]` / `[EMAIL]` placeholders.
- Each draft's `exposure_id` matches a real `Exposure.id`, and its `procedure`
  is the one looked up for that exposure.
- Confirm no network egress to any `action_url`: nothing was submitted, and
  `mark_sent()` was not called.
