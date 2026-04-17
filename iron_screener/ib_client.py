"""
IBKR connection and market-data helpers for US equity options screening.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import List, Optional, Tuple

from ib_insync import IB, Option, Stock

logger = logging.getLogger(__name__)


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

    def get_underlying_mid(self, stock: Stock, wait_seconds: float = 2.0) -> float:
        """Mid price from bid/ask, or last/close fallback."""
        self._ib.reqMktData(stock, "", False, False)
        try:
            self._ib.waitOnUpdate(timeout=wait_seconds)
            t = stock.ticker
            if t is None:
                raise RuntimeError("No ticker object after market data request.")
            bid = t.bid
            ask = t.ask
            if bid and ask and bid > 0 and ask > 0:
                return float((bid + ask) / 2)
            if t.last and t.last > 0:
                return float(t.last)
            if t.close and t.close > 0:
                return float(t.close)
            raise RuntimeError(
                f"No usable price for {stock.symbol}: bid={bid} ask={ask} last={t.last}"
            )
        finally:
            self._ib.cancelMktData(stock)

    def get_option_chain(self, stock: Stock) -> Tuple[List[str], List[float]]:
        """
        Return (sorted expirations, sorted strikes) for this underlying.

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
                return exps, strikes
        for d in details:
            if d.strikes and d.expirations:
                exps = sorted(d.expirations)
                strikes = sorted(float(s) for s in d.strikes)
                return exps, strikes
        raise RuntimeError(f"No strikes/expirations in option params for {stock.symbol}")

    @staticmethod
    def nearest_monthly_expiration(
        expirations: List[str],
        as_of: Optional[date] = None,
    ) -> Optional[str]:
        """
        Pick the nearest future expiration whose date is the 3rd Friday (standard monthly).

        If none match, return the earliest future expiration string (any style).
        """
        as_of = as_of or date.today()
        future: List[Tuple[date, str]] = []
        for exp in expirations:
            try:
                d = datetime.strptime(exp, "%Y%m%d").date()
            except ValueError:
                continue
            if d > as_of:
                future.append((d, exp))

        if not future:
            return None

        future.sort(key=lambda x: x[0])

        def is_third_friday(d: date) -> bool:
            return d.weekday() == 4 and 15 <= d.day <= 21

        for d, exp in future:
            if is_third_friday(d):
                return exp
        # No monthly pattern matched; use nearest listed expiration
        return future[0][1]

    @staticmethod
    def nearest_strike(strikes: List[float], target: float) -> float:
        """Choose the listed strike closest to target (ties: lower strike)."""
        if not strikes:
            raise ValueError("Empty strike list")
        return min(strikes, key=lambda s: (abs(s - target), s))

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

    def get_option_mid(self, contract: Option, wait_seconds: float = 2.0) -> float:
        """Bid/ask mid for one option; falls back to last/close."""
        self._ib.reqMktData(contract, "", False, False)
        try:
            self._ib.waitOnUpdate(timeout=wait_seconds)
            t = contract.ticker
            if t is None:
                raise RuntimeError("No ticker on option contract.")
            bid = t.bid
            ask = t.ask
            if bid and ask and bid > 0 and ask > 0:
                return float((bid + ask) / 2)
            if t.last and t.last > 0:
                return float(t.last)
            if t.close and t.close > 0:
                return float(t.close)
            raise RuntimeError(
                f"No price for {contract.localSymbol}: bid={bid} ask={ask}"
            )
        finally:
            self._ib.cancelMktData(contract)
