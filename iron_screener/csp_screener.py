from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Sequence

import pandas as pd

from iron_screener.yfinance_client import YFinanceClient, bs_put_delta, monthly_expirations

logger = logging.getLogger(__name__)

RESULT_COLUMNS: List[str] = [
    "Stock",
    "Expiration",
    "DTE",
    "% Distance",
    "Strike",
    "Premium",
    "Delta",
    "Stock Price",
    "SMA 200",
    "% Stock Dist SMA",
    "% Strike Dist SMA",
    "RSI 14",
    "Lower BB",
    "% Strike Dist Lower BB"
]

class CSPScreener:
    def __init__(
        self,
        client: YFinanceClient,
        mkt_data_wait: float = 15.0,
    ) -> None:
        self._client = client
        self._mkt_data_wait = mkt_data_wait

    def screen_ticker_many(
        self,
        symbol: str,
        distance_pcts: Sequence[float],
        min_dte: int,
        max_dte: int,
        monthly_only: bool,
    ) -> List[pd.Series]:
        sym = symbol.upper().strip()
        stock = self._client.qualify_stock(sym)
        spot = self._client.get_underlying_mid(stock, wait_seconds=self._mkt_data_wait)
        
        indicators = self._client.get_technical_indicators(
            stock, 
            sr_lookback=60, 
            atr_period=14
        )

        all_expirations = self._client.get_expirations(stock)
        if all_expirations is None or all_expirations.empty:
            logger.warning("%s: no future expirations in chain.", sym)
            return []

        rows: List[pd.Series] = []
        today = pd.Timestamp.now().normalize()

        monthly_dates = set()
        if monthly_only:
            monthly_dates = set(monthly_expirations(all_expirations, as_of=today.date()))

        for exp_str in all_expirations:
            try:
                if monthly_only and exp_str not in monthly_dates:
                    continue

                exp_date = pd.to_datetime(exp_str)
                dte = (exp_date - today).days

                if not (min_dte <= dte <= max_dte):
                    continue

                logger.info("Processing %s for expiration %s (DTE: %d)", sym, exp_str, dte)
                chain_df = self._client.get_chain_df(stock, exp_str)
                strikes = pd.Series(chain_df["strike"].unique(), dtype=float).sort_values(
                    kind="mergesort"
                )

                for distance_pct in distance_pcts:
                    target_sp = spot * (1.0 - float(distance_pct))
                    try:
                        short_put_k = self._client.nearest_strike(strikes, target_sp)
                        mid_sp = self._client.leg_mid_from_chain(chain_df, short_put_k, "P")
                    except Exception:
                        continue

                    # Get IV for Delta calculation
                    m = (chain_df["right"] == "P") & (pd.to_numeric(chain_df["strike"], errors="coerce") == short_put_k)
                    row = chain_df.loc[m]
                    iv = float('nan')
                    if not row.empty:
                        iv_val = row.iloc[0].get("impliedVolatility")
                        if pd.notna(iv_val):
                            iv = float(iv_val)

                    T = dte / 365.25
                    delta = bs_put_delta(spot, short_put_k, T, 0.05, iv)

                    # Calculations
                    stock_dist_sma = (
                        round((spot - indicators.sma_200) / indicators.sma_200 * 100.0, 4)
                        if not pd.isna(indicators.sma_200) and indicators.sma_200 != 0 else pd.NA
                    )
                    strike_dist_sma = (
                        round((short_put_k - indicators.sma_200) / indicators.sma_200 * 100.0, 4)
                        if not pd.isna(indicators.sma_200) and indicators.sma_200 != 0 else pd.NA
                    )
                    strike_dist_lbb = (
                        round((short_put_k - indicators.lower_bollinger) / indicators.lower_bollinger * 100.0, 4)
                        if not pd.isna(indicators.lower_bollinger) and indicators.lower_bollinger != 0 else pd.NA
                    )

                    rows.append(
                        pd.Series(
                            {
                                "Stock": sym,
                                "Expiration": exp_str,
                                "DTE": dte,
                                "% Distance": round(float(distance_pct) * 100.0, 4),
                                "Strike": float(short_put_k),
                                "Premium": round(float(mid_sp), 4),
                                "Delta": round(delta, 4) if not pd.isna(delta) else pd.NA,
                                "Stock Price": round(spot, 4),
                                "SMA 200": round(indicators.sma_200, 4) if not pd.isna(indicators.sma_200) else pd.NA,
                                "% Stock Dist SMA": stock_dist_sma,
                                "% Strike Dist SMA": strike_dist_sma,
                                "RSI 14": round(indicators.rsi_14, 4) if not pd.isna(indicators.rsi_14) else pd.NA,
                                "Lower BB": round(indicators.lower_bollinger, 4) if not pd.isna(indicators.lower_bollinger) else pd.NA,
                                "% Strike Dist Lower BB": strike_dist_lbb,
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
        output_path: str = "csp_opportunities.csv",
        min_dte: int = 15,
        max_dte: int = 45,
        monthly_only: bool = False,
    ) -> pd.DataFrame:
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
