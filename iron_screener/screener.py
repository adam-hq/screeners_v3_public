"""
Orchestrates per-ticker screening and CSV export for iron condor opportunities.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import pandas as pd

from iron_screener.yfinance_client import YFinanceClient
from iron_screener.iron_condor import IronCondor

logger = logging.getLogger(__name__)


def is_third_friday(date_obj: pd.Timestamp) -> bool:
    """Checks if a given date is the third Friday of its month."""
    return date_obj.weekday() == 4 and 15 <= date_obj.day <= 21


RESULT_COLUMNS: List[str] = [
    "Stock",
    "Expiration",
    "DTE",
    "Wing Width",
    "% Distance",
    "LP Strike",
    "SP Strike",
    "SC Strike",
    "LC Strike",
    "Premium",
    "Max Risk",
    "Premium/Wing Ratio",
    "LP Mid",
    "SP Mid",
    "SC Mid",
    "LC Mid",
    "% SP Dist to Supp",
    "% SC Dist to Res",
    "ATR",
    "Support",
    "Resistance",
]


class Screener:
    """
    Walks a ticker list, builds nearest-monthly iron condors at a % OTM distance,
    prices legs with delayed quotes, and writes a CSV report.
    """

    def __init__(
        self,
        client: YFinanceClient,
        wing_widths: List[float],
        mkt_data_wait: float = 15.0,
        sr_lookback_days: int = 60,
        atr_period: int = 14,
    ) -> None:
        self._client = client
        self._wing_widths = sorted(wing_widths)
        self._mkt_data_wait = mkt_data_wait
        self._sr_lookback_days = sr_lookback_days
        self._atr_period = atr_period

    def screen_ticker_many(
        self,
        symbol: str,
        distance_pcts: Sequence[float],
        min_dte: int,
        max_dte: int,
        monthly_only: bool,
    ) -> List[pd.Series]:
        """
        Screen one symbol for multiple distances, expirations, and wing widths.
        """
        sym = symbol.upper().strip()
        stock = self._client.qualify_stock(sym)
        spot = self._client.get_underlying_mid(stock, wait_seconds=self._mkt_data_wait)
        
        indicators = self._client.get_technical_indicators(
            stock, 
            sr_lookback=self._sr_lookback_days, 
            atr_period=self._atr_period
        )

        all_expirations = self._client.get_expirations(stock)
        if all_expirations is None or all_expirations.empty:
            logger.warning("%s: no future expirations in chain.", sym)
            return []

        rows: List[pd.Series] = []
        today = pd.Timestamp.now().normalize()

        for exp_str in all_expirations:
            try:
                exp_date = pd.to_datetime(exp_str)
                dte = (exp_date - today).days

                if not (min_dte <= dte <= max_dte):
                    continue

                if monthly_only and not is_third_friday(exp_date):
                    continue

                logger.info("Processing %s for expiration %s (DTE: %d)", sym, exp_str, dte)
                chain_df = self._client.get_chain_df(stock, exp_str)
                strikes = pd.Series(chain_df["strike"].unique(), dtype=float).sort_values(
                    kind="mergesort"
                )

                for distance_pct in distance_pcts:
                    for wing_width in self._wing_widths:
                        target_sp = spot * (1.0 - float(distance_pct))
                        target_sc = spot * (1.0 + float(distance_pct))
                        short_put_k = self._client.nearest_strike(strikes, target_sp)
                        short_call_k = self._client.nearest_strike(strikes, target_sc)

                        target_lp = short_put_k - wing_width
                        target_lc = short_call_k + wing_width
                        long_put_k = self._client.nearest_strike(strikes, target_lp)
                        long_call_k = self._client.nearest_strike(strikes, target_lc)

                        if not (long_put_k < short_put_k < short_call_k < long_call_k):
                            continue

                        mid_lp = self._client.leg_mid_from_chain(chain_df, long_put_k, "P")
                        mid_sp = self._client.leg_mid_from_chain(chain_df, short_put_k, "P")
                        mid_sc = self._client.leg_mid_from_chain(chain_df, short_call_k, "C")
                        mid_lc = self._client.leg_mid_from_chain(chain_df, long_call_k, "C")

                        ic = IronCondor(
                            symbol=sym,
                            expiration=exp_str,
                            long_put_strike=long_put_k,
                            short_put_strike=short_put_k,
                            short_call_strike=short_call_k,
                            long_call_strike=long_call_k,
                            wing_width=wing_width,
                            distance_pct=float(distance_pct),
                        )
                        net_credit, max_risk, _ = ic.metrics(mid_lp, mid_sp, mid_sc, mid_lc)
                        prem_wing_ratio = (net_credit / wing_width) if wing_width > 0 else 0.0

                        sp_dist_to_supp = (
                            round(abs(float(short_put_k - indicators.support)) / float(indicators.support) * 100.0, 4) 
                            if not pd.isna(indicators.support) and float(indicators.support) != 0 else pd.NA
                        )
                        sc_dist_to_res = (
                            round(abs(float(short_call_k - indicators.resistance)) / float(indicators.resistance) * 100.0, 4) 
                            if not pd.isna(indicators.resistance) and float(indicators.resistance) != 0 else pd.NA
                        )

                        rows.append(
                            pd.Series(
                                {
                                    "Stock": sym,
                                    "Expiration": exp_str,
                                    "DTE": dte,
                                    "Wing Width": wing_width,
                                    "% Distance": round(float(distance_pct) * 100.0, 4),
                                    "LP Strike": float(long_put_k),
                                    "SP Strike": float(short_put_k),
                                    "SC Strike": float(short_call_k),
                                    "LC Strike": float(long_call_k),
                                    "Premium": round(float(net_credit), 4),
                                    "Max Risk": round(float(max_risk), 4),
                                    "Premium/Wing Ratio": round(prem_wing_ratio, 4),
                                    "LP Mid": round(float(mid_lp), 4),
                                    "SP Mid": round(float(mid_sp), 4),
                                    "SC Mid": round(float(mid_sc), 4),
                                    "LC Mid": round(float(mid_lc), 4),
                                    "% SP Dist to Supp": sp_dist_to_supp,
                                    "% SC Dist to Res": sc_dist_to_res,
                                    "ATR": round(indicators.atr, 4) if not pd.isna(indicators.atr) else pd.NA,
                                    "Support": round(indicators.support, 4) if not pd.isna(indicators.support) else pd.NA,
                                    "Resistance": round(indicators.resistance, 4) if not pd.isna(indicators.resistance) else pd.NA,
                                }
                            )
                        )
            except Exception as e:
                logger.error(
                    "Failed processing %s for expiration %s: %s",
                    sym,
                    exp_str,
                    e,
                    exc_info=False,
                )

        return rows

    def run(
        self,
        tickers: Iterable[str],
        distance_pcts: Sequence[float],
        output_path: str = "ic_opportunities.csv",
        min_dte: int = 15,
        max_dte: int = 45,
        monthly_only: bool = False,
    ) -> pd.DataFrame:
        """
        Screen all tickers and write ``output_path`` (CSV).
        """
        dist_list = [float(x) for x in distance_pcts]

        rows: List[pd.Series] = []
        for raw in tickers:
            sym = raw.strip()
            if not sym:
                continue
            try:
                rows.extend(
                    self.screen_ticker_many(
                        sym,
                        dist_list,
                        min_dte=min_dte,
                        max_dte=max_dte,
                        monthly_only=monthly_only,
                    )
                )
            except Exception as e:
                logger.error("Failed to screen %s: %s", sym, e, exc_info=False)

        df = pd.DataFrame(rows, columns=RESULT_COLUMNS) if rows else pd.DataFrame(columns=RESULT_COLUMNS)

        path = Path(output_path)
        df.to_csv(path, index=False, encoding="utf-8")

        logger.info("Wrote %s row(s) to %s", len(df), path.resolve())
        return df
