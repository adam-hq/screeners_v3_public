"""
IBKR connection and market-data helpers for US equity options screening.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import date, datetime
from typing import Optional, Tuple, Union

import pandas as pd
from ib_insync import IB, Option, Stock

logger = logging.getLogger(__name__)


def _positive_finite(x: object) -> bool:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return math.isfinite(v) and v > 0


class IBClient:
    """
    Thin wrapper around ib_insync.IB for TWS / IB Gateway.

    Handles connection lifecycle, delayed data mode, contract qualification,
    underlying quotes, option chain discovery, and per-leg option quotes.
    """

    def __init__(self) -> None:
        self._ib = IB()

    @property
    def ib(self) -> IB:
        return self._ib

    def connect(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
        timeout: float = 10.0,
    ) -> None:
        """
        Connect to TWS (7497 paper / 7496 live typical) or Gateway (4002 / 4001).

        Raises ConnectionRefusedError and OSError from ib_insync on failure.
        """
        try:
            self._ib.connect(host, port, clientId=client_id, timeout=timeout)
        except Exception as e:
            logger.exception("Failed to connect to IBKR at %s:%s", host, port)
            raise RuntimeError(
                f"Could not connect to TWS/Gateway at {host}:{port}. "
                "Ensure the session is running and API connections are enabled."
            ) from e

        # 3 = delayed market data (e.g. 15-minute delayed for US equities)
        self._ib.reqMarketDataType(3)
        logger.info("Connected; market data type set to delayed (3).")

    def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()
            logger.info("Disconnected from IBKR.")

    def qualify_stock(self, symbol: str) -> Stock:
        """Build and qualify a US stock contract on SMART."""
        c = Stock(symbol.upper(), "SMART", "USD")
        qualified = self._ib.qualifyContracts(c)
        if not qualified:
            raise ValueError(f"Could not qualify stock contract for {symbol!r}")
        return qualified[0]

    def get_underlying_mid(self, stock: Stock, wait_seconds: float = 15.0) -> float:
        """Mid price from bid/ask, or last/close fallback."""
        t = self._ib.reqMktData(stock, "", False, False)
        try:
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                self._ib.waitOnUpdate(timeout=min(1.0, deadline - time.monotonic()))
                if t is None:
                    raise RuntimeError("No ticker object after market data request.")
                bid = t.bid
                ask = t.ask
                if _positive_finite(bid) and _positive_finite(ask):
                    return float((bid + ask) / 2)
                if _positive_finite(getattr(t, "last", None)):
                    return float(t.last)
                if _positive_finite(getattr(t, "close", None)):
                    return float(t.close)
            bid = t.bid
            ask = t.ask
            raise RuntimeError(
                f"No usable price for {stock.symbol}: bid={bid} ask={ask} last={t.last}"
            )
        finally:
            self._ib.cancelMktData(stock)

    def get_option_chain(self, stock: Stock) -> Tuple[pd.Series, pd.Series]:
        """
        Return (sorted expirations, sorted strikes) as Series for this underlying.

        Uses SMART/CBOE consolidated chain when available; strikes apply across listed expirations.
        """
        details = self._ib.reqSecDefOptParams(
            stock.symbol, "", stock.secType, stock.conId
        )
        if not details:
            raise RuntimeError(f"No option chain metadata for {stock.symbol}")

        for d in details:
            if d.exchange in ("SMART", "CBOE") and d.strikes and d.expirations:
                exps = sorted(d.expirations)
                strikes = sorted(float(s) for s in d.strikes)
                return (
                    pd.Series(exps, name="expiration"),
                    pd.Series(strikes, dtype=float, name="strike"),
                )
        for d in details:
            if d.strikes and d.expirations:
                exps = sorted(d.expirations)
                strikes = sorted(float(s) for s in d.strikes)
                return (
                    pd.Series(exps, name="expiration"),
                    pd.Series(strikes, dtype=float, name="strike"),
                )
        raise RuntimeError(f"No strikes/expirations in option params for {stock.symbol}")

    @staticmethod
    def nearest_monthly_expiration(
        expirations: Union[pd.Series, list],
        as_of: Optional[date] = None,
    ) -> Optional[str]:
        """
        Pick the nearest future expiration whose date is the 3rd Friday (standard monthly).

        If none match, return the earliest future expiration string (any style).
        """
        as_of = as_of or date.today()
        exp_s = pd.Series(expirations, dtype="string").dropna()
        if exp_s.empty:
            return None

        rows = []
        for exp in exp_s.astype(str).str.strip():
            try:
                d = datetime.strptime(exp, "%Y%m%d").date()
            except ValueError:
                continue
            if d > as_of:
                rows.append({"expiration": exp, "dt": d})

        if not rows:
            return None

        df = pd.DataFrame(rows).sort_values("dt", kind="mergesort")

        def is_third_friday(d: date) -> bool:
            return d.weekday() == 4 and 15 <= d.day <= 21

        mask = df["dt"].map(is_third_friday)
        if mask.any():
            return str(df.loc[mask, "expiration"].iloc[0])
        return str(df["expiration"].iloc[0])

    @staticmethod
    def nearest_strike(strikes: Union[pd.Series, list], target: float) -> float:
        """Choose the listed strike closest to target (ties: lower strike)."""
        s = pd.Series(strikes, dtype=float).dropna()
        if s.empty:
            raise ValueError("Empty strike list")
        diff = (s - target).abs()
        min_d = diff.min()
        return float(s.loc[diff == min_d].min())

    def qualify_option(
        self,
        symbol: str,
        expiration: str,
        strike: float,
        right: str,
        exchange: str = "SMART",
    ) -> Option:
        right = right.upper()
        if right not in ("C", "P"):
            raise ValueError("right must be 'C' or 'P'")
        opt = Option(symbol, expiration, strike, right, exchange)
        qualified = self._ib.qualifyContracts(opt)
        if not qualified:
            raise ValueError(
                f"Could not qualify option {symbol} {expiration} {strike} {right}"
            )
        return qualified[0]

    def get_option_mid(self, contract: Option, wait_seconds: float = 15.0) -> float:
        """Bid/ask mid for one option; falls back to last/close."""
        t = self._ib.reqMktData(contract, "", False, False)
        try:
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                self._ib.waitOnUpdate(timeout=min(1.0, deadline - time.monotonic()))
                if t is None:
                    raise RuntimeError("No ticker on option contract.")
                bid = t.bid
                ask = t.ask
                if _positive_finite(bid) and _positive_finite(ask):
                    return float((bid + ask) / 2)
                if _positive_finite(getattr(t, "last", None)):
                    return float(t.last)
                if _positive_finite(getattr(t, "close", None)):
                    return float(t.close)
            bid = t.bid
            ask = t.ask
            raise RuntimeError(
                f"No price for {contract.localSymbol}: bid={bid} ask={ask}"
            )
        finally:
            self._ib.cancelMktData(contract)
