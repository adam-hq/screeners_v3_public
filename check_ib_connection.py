#!/usr/bin/env python3
"""
Check IBKR TWS / IB Gateway API connectivity (ib_insync).

Usage (use the venv that has ib_insync installed):
  ibkr_venv\\Scripts\\python.exe check_ib_connection.py
  ibkr_venv\\Scripts\\python.exe check_ib_connection.py --port 7496 --client-id 101

Exit codes: 0 = connected successfully, 1 = failure or not connected.
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether Python can connect to TWS/Gateway."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Hostname (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7496,
        help="API port: 7497=TWS paper, 7496=TWS live, 4002=Gateway paper, 4001=Gateway live (default: 7496)",
    )
    parser.add_argument(
        "--client-id",
        type=int,
        default=7,
        dest="client_id",
        help="API client Id (default: 7)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Connection timeout in seconds (default: 15)",
    )
    args = parser.parse_args()

    # eventkit (used by ib_insync) needs an event loop before import on some Python versions
    asyncio.set_event_loop(asyncio.new_event_loop())

    from ib_insync import IB

    ib = IB()
    try:
        ib.connect(
            args.host,
            args.port,
            clientId=args.client_id,
            timeout=args.timeout,
        )
    except Exception as e:
        print(f"Connection failed: {e}")
        return 1

    if ib.isConnected():
        print("Status: ACTIVE (connected)")
        ib.disconnect()
        print("Status: CLOSED (after disconnect)")
        return 0

    print("Status: CLOSED (connect returned but session not active)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
