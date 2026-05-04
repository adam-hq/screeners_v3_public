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
from iron_screener.ic_screener import Screener


def _parse_csv_list_ic(s: str) -> List[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _parse_distances_ic(s: str) -> List[float]:
    """
    Parse distances from CLI.

    Accepts:
    - "0.03,0.05" (fractions)
    - "3,5,10" (percents)
    - "3%, 5%, 10%" (percents)
    """
    out: List[float] = []
    for raw in _parse_csv_list_ic(s):
        token = raw.replace("%", "").strip()
        v = float(token)
        out.append(v / 100.0 if v > 1.0 else v)
    return out


def _parse_wing_widths_ic(s: str) -> List[float]:
    """
    Parse comma-separated wing widths.
    Accepts: "2.5, 5, 10"
    """
    out: List[float] = []
    for raw in _parse_csv_list_ic(s):
        try:
            out.append(float(raw))
        except ValueError:
            pass
    return out

def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="yfinance iron condor screener")
    p.add_argument(
        "--symbols",
        default="TSLA,AMZN,GOOGL,AAPL,MSFT,WMT",
        help="Comma-separated symbols (e.g. TSLA,AMZN,GOOGL)",
    )
    p.add_argument(
        "--min-dte",
        type=int,
        default=15,
        help="Minimum Days to Expiry (DTE).",
    )
    p.add_argument(
        "--max-dte",
        type=int,
        default=45,
        help="Maximum Days to Expiry (DTE).",
    )
    p.add_argument(
        "--monthly-only",
        action="store_true",
        help="If set, only evaluates major monthly expirations (3rd Friday).",
    )
    p.add_argument(
        "--distances",
        default="3,5,8,10,15,20",
        help="Comma-separated distances as percent or fraction (e.g. 3,5,10 or 0.03,0.05)",
    )
    p.add_argument(
        "--wing-widths",
        default="2.5,5.0",
        help="Comma-separated wing widths to evaluate (default: 2.5,5.0)",
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

    tickers = _parse_csv_list_ic(args.symbols)
    distances = _parse_distances_ic(args.distances)
    wing_widths = _parse_wing_widths_ic(args.wing_widths)

    client = YFinanceClient()
    screener = Screener(client, wing_widths=wing_widths)
    screener.run(
        tickers,
        distance_pcts=distances,
        output_path=str(args.output),
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        monthly_only=args.monthly_only,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
