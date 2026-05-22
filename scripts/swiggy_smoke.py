#!/usr/bin/env python3
"""Phase 0.E3 — smoke test: get_addresses via Swiggy Food JSON-RPC."""

import asyncio
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phases.phase_00.services.swiggy_api import SwiggyApiClient, SwiggyApiError
from phases.phase_00.services.swiggy_auth import SwiggyAuthError, SwiggyAuthService


async def main() -> int:
    auth = SwiggyAuthService()
    if not auth.get_access_token():
        print("Not authenticated.")
        print("  1. Copy .env.example → .env and set SWIGGY_OAUTH_CLIENT_ID")
        print("  2. Start API: uvicorn backend.main:app --reload --port 8000")
        print("  3. Open http://localhost:8000/auth/swiggy/login")
        return 1

    client = SwiggyApiClient()
    try:
        data = await client.get_addresses()
    except (SwiggyAuthError, SwiggyApiError) as exc:
        print(f"get_addresses failed: {exc}")
        return 1

    print("get_addresses OK")
    if isinstance(data, list):
        print(f"  {len(data)} address(es)")
        for addr in data[:3]:
            if isinstance(addr, dict):
                print(f"  - {addr.get('id', addr.get('addressId', '?'))}: {addr.get('label', addr.get('address', '?'))}")
    else:
        print(f"  response: {data!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
