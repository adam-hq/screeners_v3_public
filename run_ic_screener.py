#!/usr/bin/env python3
"""
IronScreener — yfinance iron condor screener (delayed data, monthly expirations).

Usage:
    python run_ic_screener.py --symbols TSLA,AMZN,GOOGL,AAPL,MSFT,WMT --distances 3,5,8,10,15,20
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List

from iron_screener.yfinance_client import YFinanceClient
from iron_screener.screener import Screener


def _parse_csv_list(s: str) -> List[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _parse_distances(s: str) -> List[float]:
    """
    Parse distances from CLI.

    Accepts:
    - "0.03,0.05" (fractions)
    - "3,5,10" (percents)
    - "3%, 5%, 10%" (percents)
    """
    out: List[float] = []
    for raw in _parse_csv_list(s):
        token = raw.replace("%", "").strip()
        v = float(token)
        out.append(v / 100.0 if v > 1.0 else v)
    return out


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="yfinance iron condor screener")
    p.add_argument(
        "--symbols",
        default="TSLA,AMZN,GOOGL,AAPL,MSFT,WMT",
        help="Comma-separated symbols (e.g. TSLA,AMZN,GOOGL)",
    )
    p.add_argument(
        "--expiry",
        default=None,
        help="Option expiration in YYYY-MM-DD. If omitted, uses nearest monthly expiration.",
    )
    p.add_argument(
        "--distances",
        default="3,5,8,10,15,20",
        help="Comma-separated distances as percent or fraction (e.g. 3,5,10 or 0.03,0.05)",
    )
    p.add_argument(
        "--wing-width",
        type=float,
        default=5.0,
        help="Wing width in dollars (default: 5.0)",
    )
    p.add_argument(
        "--output",
        default="ic_opportunities.csv",
        help="Output CSV path (default: ic_opportunities.csv)",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR). Default INFO.",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tickers = _parse_csv_list(args.symbols)
    distances = _parse_distances(args.distances)

    client = YFinanceClient()
    screener = Screener(client, wing_width=float(args.wing_width))
    screener.run(
        tickers,
        distance_pcts=distances,
        output_path=str(args.output),
        expiry=(str(args.expiry).strip() if args.expiry else None),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
