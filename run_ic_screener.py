#!/usr/bin/env python3
"""
IronScreener — IBKR iron condor screener (delayed data, monthly expirations).

Run with TWS or IB Gateway running and API enabled. Default port 7497 (TWS paper).

Usage:
    python run_ic_screener.py
"""

from __future__ import annotations

import asyncio
import logging
import sys

# eventkit (ib_insync) expects an event loop before import on some Python versions
asyncio.set_event_loop(asyncio.new_event_loop())

from iron_screener.ib_client import IBClient
from iron_screener.screener import Screener


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # --- Input: US stock tickers (NYSE/NASDAQ via SMART routing) ---
    #tickers = ["TSLA", "AMZN", "GOOGL", "AAPL", "MSFT", "WMT"]
    tickers = ["GOOGL"]
    # Short legs: this fraction away from spot (0.10 = 10% OTM put / 10% OTM call)
    distance_pct = 0.10

    # Protective long wings: $5 wide spreads (change per your risk preference)
    wing_width = 5.0

    # IBKR connection (TWS paper default)
    host = "127.0.0.1"
    port = 7496
    client_id = 1

    output_csv = "ic_opportunities.csv"

    client = IBClient()
    try:
        client.connect(host=host, port=port, client_id=client_id)
    except RuntimeError as e:
        logging.error("%s", e)
        return 1

    try:
        screener = Screener(client, wing_width=wing_width)
        screener.run(tickers, distance_pct=distance_pct, output_path=output_csv)
    finally:
        client.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
