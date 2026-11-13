---
name: discover_exposure
description: Stage 1 — Discover generic data brokers via identifier-free Tavily search + Nemotron 3 Nano classification, then match the adult synthetic family strictly locally against RFC 2606 .example fixtures.
---

# Stage 1: Inventory Discovery & Local Matching

Corresponds to `discover_inventory()` and `match_local_listings()` in `src/haven/pipeline.py`.

## Rules

1. **Zero-PII outbound search:** `discover_inventory()` only issues fixed, person-free category queries (`research.INVENTORY_QUERIES`). Every outbound payload passes `haven.privacy.check()` before SDK construction.
2. **Nano classification:** Nemotron 3 Nano classifies whether a search result is a `people_search`, `data_broker`, `social`, or `other` site and tags coverage as `local_fixture` or `manual_only`.
3. **Purely local matching:** `match_local_listings()` matches the deterministic adult household (`Avery Synthwell`, `Jordan Synthwell`) against local fixtures (`haven.fixtures.load_listings()`) with zero network calls:
   * `verified`: exact name/alias plus at least one confirming identifier.
   * `candidate`: exact name/alias with no contradicting location.
   * `rejected`: exact name match whose stated location contradicts `Sampleville, CA` (never sent to downstream extraction or drafting).
4. **Redacted snippets:** `evidence_snippet` summarizes only matched identifier kinds and stated location, never raw high-sensitivity values.
