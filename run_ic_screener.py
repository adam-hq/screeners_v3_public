#!/usr/bin/env python3
"""
IronScreener — yfinance iron condor screener (delayed data, monthly expirations).

Usage:
    python run_ic_screener.py
"""

from __future__ import annotations

import logging
import sys

from iron_screener.yfinance_client import YFinanceClient
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

    output_csv = "ic_opportunities.csv"

    client = YFinanceClient()
    screener = Screener(client, wing_width=wing_width)
    screener.run(tickers, distance_pct=distance_pct, output_path=output_csv)

    return 0


if __name__ == "__main__":
    sys.exit(main())
