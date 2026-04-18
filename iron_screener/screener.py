"""
Orchestrates per-ticker screening and CSV export for iron condor opportunities.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

from iron_screener.yfinance_client import YFinanceClient
from iron_screener.iron_condor import IronCondor

logger = logging.getLogger(__name__)

RESULT_COLUMNS: List[str] = [
    "Stock",
    "Expiration",
    "Strikes (LP/SP/SC/LC)",
    "% Distance",
    "Total Premium",
    "R/R Ratio",
]


class Screener:
    """
    Walks a ticker list, builds nearest-monthly iron condors at a % OTM distance,
    prices legs with delayed quotes, and writes a CSV report.
    """

    def __init__(
        self,
        client: YFinanceClient,
        wing_width: float = 5.0,
        mkt_data_wait: float = 15.0,
    ) -> None:
        self._client = client
        self._wing_width = wing_width
        self._mkt_data_wait = mkt_data_wait

    @property
    def wing_width(self) -> float:
        return self._wing_width

    def screen_ticker(self, symbol: str, distance_pct: float) -> Optional[pd.Series]:
        """
        Return one result row as a Series for ``symbol``, or None if skipped.

        ``distance_pct`` is fractional OTM for short legs, e.g. 0.10 => 10% below/above spot.
        """
        sym = symbol.upper().strip()
        stock = self._client.qualify_stock(sym)
        spot = self._client.get_underlying_mid(stock, wait_seconds=self._mkt_data_wait)

        expirations = self._client.get_expirations(stock)
        exp = self._client.nearest_monthly_expiration(expirations)
        if not exp:
            logger.warning("%s: no future expirations in chain.", sym)
            return None

        chain_df = self._client.get_chain_df(stock, exp)
        strikes = pd.Series(chain_df["strike"].unique(), dtype=float).sort_values(kind="mergesort")

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

        mid_lp = self._client.leg_mid_from_chain(chain_df, long_put_k, "P")
        mid_sp = self._client.leg_mid_from_chain(chain_df, short_put_k, "P")
        mid_sc = self._client.leg_mid_from_chain(chain_df, short_call_k, "C")
        mid_lc = self._client.leg_mid_from_chain(chain_df, long_call_k, "C")

        ic = IronCondor(
            symbol=sym,
            expiration=exp,
            long_put_strike=long_put_k,
            short_put_strike=short_put_k,
            short_call_strike=short_call_k,
            long_call_strike=long_call_k,
            wing_width=self._wing_width,
            distance_pct=distance_pct,
        )
        net_credit, _max_risk, rr = ic.metrics(mid_lp, mid_sp, mid_sc, mid_lc)

        strikes_str = f"{long_put_k:g}/{short_put_k:g}/{short_call_k:g}/{long_call_k:g}"

        return pd.Series(
            {
                "Stock": sym,
                "Expiration": exp,
                "Strikes (LP/SP/SC/LC)": strikes_str,
                "% Distance": round(distance_pct * 100.0, 4),
                "Total Premium": round(net_credit, 4),
                "R/R Ratio": round(rr, 6) if rr is not None else pd.NA,
            }
        )

    def run(
        self,
        tickers: Iterable[str],
        distance_pct: float,
        output_path: str = "ic_opportunities.csv",
    ) -> pd.DataFrame:
        """
        Screen all tickers and write ``output_path`` (CSV).

        Returns a DataFrame of successfully screened rows (empty if none).
        """
        rows: List[pd.Series] = []
        for raw in tickers:
            sym = raw.strip()
            if not sym:
                continue
            try:
                row = self.screen_ticker(sym, distance_pct)
                if row is not None:
                    rows.append(row)
            except Exception as e:
                logger.error("Failed to screen %s: %s", sym, e, exc_info=False)

        df = pd.DataFrame(rows, columns=RESULT_COLUMNS) if rows else pd.DataFrame(columns=RESULT_COLUMNS)
        path = Path(output_path)
        df.to_csv(path, index=False, encoding="utf-8")

        logger.info("Wrote %s row(s) to %s", len(df), path.resolve())
        return df
