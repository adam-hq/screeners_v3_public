"""
Orchestrates per-ticker screening and CSV export for iron condor opportunities.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from iron_screener.ib_client import IBClient
from iron_screener.iron_condor import IronCondor

logger = logging.getLogger(__name__)


class Screener:
    """
    Walks a ticker list, builds nearest-monthly iron condors at a % OTM distance,
    prices legs with delayed quotes, and writes a CSV report.
    """

    def __init__(
        self,
        client: IBClient,
        wing_width: float = 5.0,
        mkt_data_wait: float = 2.0,
    ) -> None:
        self._client = client
        self._wing_width = wing_width
        self._mkt_data_wait = mkt_data_wait

    @property
    def wing_width(self) -> float:
        return self._wing_width

    def screen_ticker(self, symbol: str, distance_pct: float) -> Optional[Dict[str, Any]]:
        """
        Return one result row dict for ``symbol``, or None if skipped.

        ``distance_pct`` is fractional OTM for short legs, e.g. 0.10 => 10% below/above spot.
        """
        sym = symbol.upper().strip()
        stock = self._client.qualify_stock(sym)
        spot = self._client.get_underlying_mid(stock, wait_seconds=self._mkt_data_wait)

        expirations, strikes = self._client.get_option_chain(stock)
        exp = self._client.nearest_monthly_expiration(expirations)
        if not exp:
            logger.warning("%s: no future expirations in chain.", sym)
            return None

        # Target short strikes from spot (puts below, calls above)
        target_sp = spot * (1.0 - distance_pct)
        target_sc = spot * (1.0 + distance_pct)
        short_put_k = self._client.nearest_strike(strikes, target_sp)
        short_call_k = self._client.nearest_strike(strikes, target_sc)

        target_lp = short_put_k - self._wing_width
        target_lc = short_call_k + self._wing_width
        long_put_k = self._client.nearest_strike(strikes, target_lp)
        long_call_k = self._client.nearest_strike(strikes, target_lc)

        if not (long_put_k < short_put_k < short_call_k < long_call_k):
            logger.warning(
                "%s: invalid strike ordering LP=%s SP=%s SC=%s LC=%s — skipping.",
                sym,
                long_put_k,
                short_put_k,
                short_call_k,
                long_call_k,
            )
            return None

        lp = self._client.qualify_option(sym, exp, long_put_k, "P")
        sp = self._client.qualify_option(sym, exp, short_put_k, "P")
        sc = self._client.qualify_option(sym, exp, short_call_k, "C")
        lc = self._client.qualify_option(sym, exp, long_call_k, "C")

        mid_lp = self._client.get_option_mid(lp, wait_seconds=self._mkt_data_wait)
        mid_sp = self._client.get_option_mid(sp, wait_seconds=self._mkt_data_wait)
        mid_sc = self._client.get_option_mid(sc, wait_seconds=self._mkt_data_wait)
        mid_lc = self._client.get_option_mid(lc, wait_seconds=self._mkt_data_wait)

        ic = IronCondor(
            symbol=sym,
            expiration=exp,
            long_put=lp,
            short_put=sp,
            short_call=sc,
            long_call=lc,
            wing_width=self._wing_width,
            distance_pct=distance_pct,
        )
        net_credit, _max_risk, rr = ic.metrics(mid_lp, mid_sp, mid_sc, mid_lc)

        strikes_str = f"{long_put_k:g}/{short_put_k:g}/{short_call_k:g}/{long_call_k:g}"

        return {
            "Stock": sym,
            "Expiration": exp,
            "Strikes (LP/SP/SC/LC)": strikes_str,
            "% Distance": round(distance_pct * 100.0, 4),
            "Total Premium": round(net_credit, 4),
            "R/R Ratio": round(rr, 6) if rr is not None else "",
        }

    def run(
        self,
        tickers: List[str],
        distance_pct: float,
        output_path: str = "ic_opportunities.csv",
    ) -> List[Dict[str, Any]]:
        """
        Screen all tickers and write ``output_path`` (CSV).

        Returns the list of row dicts successfully produced.
        """
        rows: List[Dict[str, Any]] = []
        for raw in tickers:
            sym = raw.strip()
            if not sym:
                continue
            try:
                row = self.screen_ticker(sym, distance_pct)
                if row:
                    rows.append(row)
            except Exception as e:
                logger.error("Failed to screen %s: %s", sym, e, exc_info=False)

        path = Path(output_path)
        fieldnames = [
            "Stock",
            "Expiration",
            "Strikes (LP/SP/SC/LC)",
            "% Distance",
            "Total Premium",
            "R/R Ratio",
        ]
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

        logger.info("Wrote %s row(s) to %s", len(rows), path.resolve())
        return rows
