# Haven Demo Script (2–3 Minutes)

1. **Start Haven locally (keyless or live):**
   ```bash
   python scripts/serve.py
   ```
   * Point out the **Provider Mode** badge in the top bar (`offline (simulated)` when running without keys, or `live` when `NEBIUS_API_KEY` + `TAVILY_API_KEY` are configured) and the **Token Factory host** (`api.tokenfactory.us-central1.nebius.com`).

2. **Highlight the Safeguards Before Scanning:**
   * Show the **Synthetic Demo Household** card: adults-only (`Avery Synthwell`, `Jordan Synthwell`, `Sampleville, CA`, `@example.com`, `555-01xx`) with high-sensitivity fields redacted by default (`GET /api/family`).
   * Try clicking **Run Privacy Scan** before checking the consent box — point out the disabled state (and `POST /api/scan` returning `400` without `{"consent": true}`, `422` on extra payloads, `429` past `HAVEN_SCAN_RATE_LIMIT`).

3. **Run the Scan:**
   * Check **I consent to run a privacy scan...** and click **Run Privacy Scan**.
   * Walk through the dashboard sections top-to-bottom:
     * **Broker Inventory:** Generic Tavily search + **Nemotron 3 Nano** classification distinguishing `local_fixture` vs `manual_only`.
     * **Matched Exposure Board:** Purely local exact matching distinguishing `verified` (`Spokeo`, `Whitepages`, `Radaris`, `FastPeopleSearch`), `candidate` (`BeenVerified`), and `rejected` (`TruePeopleSearch`, location mismatch).
     * **Multi-Site Strategy:** **Nemotron 3 Ultra** removal plan generated for 5+ actionable exposures.
     * **Removal Action Tracker:** **Nemotron 3 Super** placeholder-only drafts (`[FULL_NAME]`, `[LISTING_URL]`, etc.), clear distinction between **statutory legal deadlines** (with verified source URL) vs **broker service targets**, and live `Approve → Mark Sent → Confirm Removed` human-gate buttons.
     * **Egress Evidence & Tier Usage:** Honest labeling (`real` / `simulated` / `unavailable` OCSF evidence + `(simulated)` model tier badge when offline).

4. **Point to Verification & Next Steps:**
   * Show `python -m pytest tests/ -v` (`229` passing checks including `test_privacy_invariants.py` and `test_compliance_guardrails.py`), and disclose honestly that live OpenShell/Landlock and `/v1/models` checks require a Linux host with Docker/WSL and live Nebius/Tavily keys.
