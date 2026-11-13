# Haven Architecture

## 1. Security & Privacy Boundaries

Haven enforces **defense in depth** across two distinct layers:

1. **Application Outbound Payload Gate (`haven.privacy`)**
   * Every call inside `haven.research` (`tavily.search`, `tavily.extract`) and `haven.llm` (`token_factory`) passes its full outbound text through `privacy.check(channel, *payloads)` *before* constructing an HTTP/SDK client.
   * Fails closed: even before `privacy.register(family, listings)` runs, the gate protects the built-in Synthwell household and all 7 fixture listings.
   * Protected categories: full names, surname on its own, phone numbers across digit separators, email addresses & local parts, street address, `City, ST` pairs, listing URLs, and raw listing sentences (>= 24 characters).
   * Blocked errors raise `PayloadBlocked(channel, category)` without echoing the matched secret value.

2. **Process & Network Sandbox (`policy/policy.yaml`, `policy/policy.hardened.yaml`)**
   * Intended to run Haven inside NVIDIA OpenShell on Linux with Landlock filesystem restrictions and outbound HTTPS allowlisting limited strictly to `api.tokenfactory.us-central1.nebius.com`, `api.tokenfactory.nebius.com`, and `api.tavily.com` (never `integrate.api.nvidia.com` or `build.nvidia.com`).
   * *Note:* Policy files are schema-checked in `tests/test_boundary.py`; runtime enforcement via OpenShell/Landlock has not yet been executed on Linux in this environment.

---

## 2. Five-Stage Pipeline (`haven.pipeline`)

1. **Seed Family (`haven.seed`):** Generates the adults-only deterministic household (`Avery Synthwell`, `Jordan Synthwell`, `100 Fictional Way, Sampleville, CA 00000`, `@example.com`, `555-0142` / `555-0198`). No children or school identifiers exist.
2. **Stage 1a — Generic Broker Inventory (`discover_inventory`):** Sends fixed, person-free category queries via `research.search_inventory()` and classifies results using **Nemotron 3 Nano**. Sites represented in `haven.fixtures` are tagged `local_fixture`; others are tagged `manual_only`.
3. **Stage 1b — Purely Local Matching (`match_local_listings`):** Matches family identifiers strictly in-memory against the 7 synthetic `.example` fixtures:
   * `verified`: Name/alias plus at least one confirming identifier (phone, email, street address, or matching `Sampleville, CA`).
   * `candidate`: Name/alias match with no contradicting location.
   * `rejected`: Name match whose stated location contradicts `Sampleville, CA` (e.g., `Othertown, TX`). Skipped during extraction and drafting.
   * Evidence snippets are redacted to identifier kinds + location so high-sensitivity values never render on the dashboard.
4. **Stage 2 — Opt-Out Procedure Research (`extract_optout_procedures`):** For non-rejected exposures, searches and extracts public opt-out instructions by broker company name (`research.search_optout_procedure`, `research.extract_page`), fences untrusted HTML text inside `<untrusted_page_content>` tags, and extracts structured JSON via **Nemotron 3 Super**. A `statutory_deadline_days` value is saved only if both `jurisdiction` and a valid `http(s)://` `deadline_source_url` are provided (timestamped in `deadline_verified_at`), keeping a broker's own `service_target_days` cleanly separated.
5. **Stage 3a — Multi-Site Strategy (`synthesize_strategy`):** When 5 or more non-rejected exposures are present, **Nemotron 3 Ultra** sequences removals across sites (e.g., fastest self-serve suppression first, then cascading brokers).
6. **Stage 3b — Placeholder-Only Drafting & Human Gate (`draft_removal_requests`, `haven.api`):** **Nemotron 3 Super** drafts removal templates referencing only `[FULL_NAME]`, `[LISTING_URL]`, `[EMAIL]`, `[PHONE]`, and `[ADDRESS]`. Humans transition actions through `drafted → approved → sent → confirmed_removed`.

---

## 3. Evidence Integrity (`haven.evidence`)

`GET /api/evidence` and the dashboard Evidence panel distinguish three states:

* `real`: Non-empty OCSF records without `"simulated": true`.
* `simulated`: Records written locally by `write_simulated_log` (carrying `"simulated": true`).
* `unavailable`: No OpenShell OCSF log file found on disk.

Missing `bytes_out` or `request_count` values stay `None` (rendered as `—` in the UI) rather than being fabricated.
