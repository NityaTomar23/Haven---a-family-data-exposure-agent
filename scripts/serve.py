"""Run the Haven dashboard locally.

    uv run python scripts/serve.py
    python scripts/serve.py

The project deliberately sets `[tool.uv] package = false`, so `haven` is never
installed into the environment.  This entry point puts `src/` on the import path
itself, which is why `uvicorn haven.api:app` alone raises ModuleNotFoundError.

Environment:
    HAVEN_HOST   interface to bind (default 127.0.0.1 — localhost only)
    HAVEN_PORT   port to bind    (default 8000)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import uvicorn  # noqa: E402  (import after the sys.path fix)


def main() -> int:
    host = os.environ.get("HAVEN_HOST", "127.0.0.1")
    port = int(os.environ.get("HAVEN_PORT") or os.environ.get("PORT") or "8000")

    # Reload is intentionally off: the reloader re-executes in a fresh
    # interpreter that would not inherit the sys.path entry above.
    uvicorn.run("haven.api:app", host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
