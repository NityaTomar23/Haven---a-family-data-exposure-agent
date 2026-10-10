"""Verify every Nemotron tier's model id against the live Token Factory.

The nano tier's id in llm.py is UNVERIFIED: `nvidia/nemotron-3-nano-30b` does
not appear in the official Nebius cookbook, while `nvidia/nemotron-3-super-120b-a12b`
and `nvidia/Nemotron-3-Ultra-550b-a55b` do. This script is how you settle it.

    uv run python scripts/verify_models.py            # check configured tiers
    uv run python scripts/verify_models.py --list     # list everything served

Requires NEBIUS_API_KEY (and honours NEBIUS_BASE_URL). Makes a real network
call to GET /v1/models, which the sandbox policy allowlists.

Exit codes: 0 when every configured tier resolves, 1 when any tier is missing,
2 on a configuration or connection error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from haven import llm  # noqa: E402  (import after the sys.path fix)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list",
        action="store_true",
        help="print every model id the endpoint serves",
    )
    args = parser.parse_args()

    print(f"Endpoint: {llm.base_url()}")
    print(f"Permitted endpoints: {', '.join(llm.ALLOWED_TOKEN_FACTORY_BASE_URLS)}")

    try:
        result = llm.verify_models()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # network, auth, or SDK failure
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    available = result.pop("all_models")["available"]
    print(f"Endpoint serves {len(available)} models.\n")

    missing = []
    for tier in ("nano", "super", "ultra"):
        entry = result[tier]
        mark = "ok  " if entry["available"] else "MISSING"
        print(f"  {mark} {tier:<6} {entry['model']}")
        if not entry["available"]:
            missing.append(tier)

    if args.list:
        print("\nAll models:")
        for model_id in available:
            print(f"  {model_id}")

    if missing:
        print(
            f"\n{len(missing)} tier(s) unresolved: {', '.join(missing)}.\n"
            "Set the override to a model id from the list above, e.g.\n"
            "  NEBIUS_MODEL_NANO=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B\n"
            "and record the verified id in README.md.",
            file=sys.stderr,
        )
        return 1

    print("\nAll configured tiers resolved against the live endpoint.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
