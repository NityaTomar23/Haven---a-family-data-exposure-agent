---
name: draft_removal_request
description: Stage 3 — Synthesize a multi-site removal strategy with Nemotron 3 Ultra (5+ actionable exposures) and draft placeholder-only removal requests with Nemotron 3 Super. Never submit automatically.
---

# Stage 3: Strategy & Placeholder-Only Drafting

Corresponds to `synthesize_strategy()` and `draft_removal_requests()` in `src/haven/pipeline.py`.

## Rules

1. **Ultra-tier strategy gate:** Call `synthesize_strategy()` (Nemotron 3 Ultra) only when 5 or more non-rejected exposures exist.
2. **Placeholder-only prompts & drafts:** Prompts to Nemotron 3 Super contain zero family PII and zero listing URLs. Generated drafts must use `[FULL_NAME]`, `[LISTING_URL]`, `[EMAIL]`, `[PHONE]`, and `[ADDRESS]` for human completion after review.
3. **Human-in-the-loop only:** All actions start at `status="drafted"`. The agent must NEVER submit web forms, send emails, or advance actions past `drafted`. Only human actions move `drafted -> approved -> sent -> confirmed_removed`.
