#!/usr/bin/env python3
"""Run the standalone Vercel integration lifecycle backend."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add src directory to Python path for local development
src_path = Path(__file__).parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

from integration import run_server  # noqa: E402


def main() -> int:
    host = os.getenv("INTEGRATION_HOST", "127.0.0.1")
    port = int(os.getenv("INTEGRATION_PORT", "8787"))
    store_path = os.getenv(
        "INTEGRATION_STORE_PATH",
        ".ibmcloudvercel/installations.json",
    )

    try:
        run_server(host=host, port=port, store_path=store_path)
    except KeyboardInterrupt:
        print("\nIntegration service stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
