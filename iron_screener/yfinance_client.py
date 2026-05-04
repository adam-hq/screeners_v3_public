"""
Yahoo Finance (yfinance) helpers for delayed underlying + option chain data.

This is intended as a lightweight alternative data source to IBKR/TWS for
screening workflows where delayed quotes are acceptable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf


Right = Literal["C", "P"]


def norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def bs_put_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or pd.isna(sigma):
        return 0.0 if S >= K else -1.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return norm_cdf(d1) - 1.0


@dataclass(frozen=True)
class StockPrice:
    symbol: str
    price: float
    as_of: Optional[datetime] = None
    source: str = "yfinance"


@dataclass(frozen=True)
class TechnicalIndicators:
    atr: float
    support: float
    resistance: float
    sma_200: float = float('nan')
    rsi_14: float = float('nan')
    lower_bollinger: float = float('nan')


def get_stock_price(symbol: str) -> StockPrice:
    """
    Return a best-effort "current" price for the underlying.

    Notes:
    - yfinance is often delayed and may be stale.
    - We fall back across multiple fields to get something usable.
    """
    t = yf.Ticker(symbol.upper().strip())

    # Prefer fast_info when it exists; it's usually quicker than history().
    as_of: Optional[datetime] = None
    price: Optional[float] = None

    fast = getattr(t, "fast_info", None)
    if fast:
        for k in ("last_price", "lastPrice", "regular_market_price", "regularMarketPrice"):
            v = fast.get(k) if hasattr(fast, "get") else None
            if v is not None:
                try:
                    price = float(v)
                    break
                except (TypeError, ValueError):
                    pass

    if price is None:
        hist = t.history(period="5d", interval="1d")
        if hist is None or hist.empty:
            raise RuntimeError(f"No price history returned for {symbol!r}")
        price = float(hist["Close"].iloc[-1])
        # yfinance history index is typically tz-aware; keep as python datetime if available
        try:
            as_of = hist.index[-1].to_pydatetime()
        except Exception:
            as_of = None

    return StockPrice(symbol=symbol.upper().strip(), price=float(price), as_of=as_of)


def get_technical_indicators(symbol: str, sr_lookback: int = 60, atr_period: int = 14) -> TechnicalIndicators:
    """
    Fetch historical data once and calculate ATR, Support, and Resistance.
    """
    t = yf.Ticker(symbol.upper().strip())
    # We need max(sr_lookback, atr_period, 200) + 1 trading days. 
    # Fetch "1y" to ensure we have enough trading days (1 year is ~252 trading days).
    hist = t.history(period="1y", interval="1d")
    
    if hist is None or hist.empty or len(hist) < max(sr_lookback, atr_period) + 1:
        return TechnicalIndicators(atr=float('nan'), support=float('nan'), resistance=float('nan'))

    high = hist["High"]
    low = hist["Low"]
    close = hist["Close"]
    prev_close = close.shift(1)

    # True Range
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # ATR (Wilder's Smoothing usually, but simple EMA is close enough/standard for some implementations. We'll use EMA here)
    atr = tr.ewm(alpha=1/atr_period, adjust=False).mean().iloc[-1]

    # Support / Resistance
    support = low.tail(sr_lookback).min()
    resistance = high.tail(sr_lookback).max()

    # SMA 200
    if len(close) >= 200:
        sma_200 = close.rolling(window=200).mean().iloc[-1]
    else:
        sma_200 = float('nan')

    # RSI 14
    if len(close) > atr_period:
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/atr_period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/atr_period, adjust=False).mean()
        rs = gain / loss
        rsi_14 = (100 - (100 / (1 + rs))).iloc[-1]
    else:
        rsi_14 = float('nan')

    # Bollinger Bands (20-day, 2 std dev)
    if len(close) >= 20:
        sma_20 = close.rolling(window=20).mean()
        std_20 = close.rolling(window=20).std()
        lower_bollinger = (sma_20 - 2 * std_20).iloc[-1]
    else:
        lower_bollinger = float('nan')

    return TechnicalIndicators(
        atr=float(atr),
        support=float(support),
        resistance=float(resistance),
        sma_200=float(sma_200),
        rsi_14=float(rsi_14),
        lower_bollinger=float(lower_bollinger)
    )


def get_option_chain(symbol: str, expiry: str) -> pd.DataFrame:
    """
    Return a combined option chain DataFrame for the given `symbol` + `expiry`.

    The returned DataFrame is calls and puts concatenated with extra columns:
    - right: "C" or "P"
    - expiration: expiry string as passed in (usually "YYYY-MM-DD")
    - mid: (bid + ask)/2 when both are present, else NaN
    """
    sym = symbol.upper().strip()
    exp = expiry.strip()
    t = yf.Ticker(sym)

    chain = t.option_chain(exp)
    calls = chain.calls.copy()
    puts = chain.puts.copy()

    calls["right"] = "C"
    puts["right"] = "P"
    calls["expiration"] = exp
    puts["expiration"] = exp

    df = pd.concat([calls, puts], ignore_index=True, sort=False)

    # Standardize types a bit; yfinance can return mixed dtypes.
    for col in ("strike", "lastPrice", "bid", "ask", "volume", "openInterest", "impliedVolatility"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "bid" in df.columns and "ask" in df.columns:
        df["mid"] = (df["bid"] + df["ask"]) / 2.0
    else:
        df["mid"] = pd.NA

    # Put a few key columns first (keep all original columns too).
    preferred = [
        "contractSymbol",
        "expiration",
        "right",
        "strike",
        "lastTradeDate",
        "lastPrice",
        "bid",
        "ask",
        "mid",
        "change",
        "percentChange",
        "volume",
        "openInterest",
        "impliedVolatility",
        "inTheMoney",
        "contractSize",
        "currency",
    ]
    cols = [c for c in preferred if c in df.columns] + [c for c in df.columns if c not in preferred]
    return df.loc[:, cols]


def get_expirations(symbol: str) -> pd.Series:
    """Return available option expirations for `symbol` as a Series of strings."""
    t = yf.Ticker(symbol.upper().strip())
    exps = list(getattr(t, "options", []) or [])
    return pd.Series(exps, dtype="string", name="expiration")


def _third_friday(year: int, month: int) -> date:
    d = date(year, month, 15)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d


def _standard_monthly_expiration(year: int, month: int, expirations: set[str]) -> Optional[str]:
    third = _third_friday(year, month)
    third_iso = third.isoformat()
    if third_iso in expirations:
        return third_iso

    candidates = [
        exp for exp in expirations
        if (date.fromisoformat(exp) < third and date.fromisoformat(exp) >= third - timedelta(days=7))
    ]
    if candidates:
        return max(candidates)
    return None


def nearest_monthly_expiration(
    expirations: pd.Series | list,
    as_of: Optional[date] = None,
) -> Optional[str]:
    """
    Pick the nearest future expiration that represents the standard monthly expiry.

    This may be the 3rd Friday or the prior trading day when the 3rd Friday is a market holiday.
    """
    monthly_exps = monthly_expirations(expirations, as_of=as_of)
    return monthly_exps[0] if monthly_exps else None


def monthly_expirations(
    expirations: pd.Series | list,
    as_of: Optional[date] = None,
) -> list[str]:
    """Return all future standard monthly expirations from the provided list."""
    as_of = as_of or date.today()
    exp_s = pd.Series(expirations, dtype="string").dropna()
    if exp_s.empty:
        return []

    expirations_set = {exp.strip() for exp in exp_s.astype(str) if exp.strip()}
    future_exps = sorted(
        exp for exp in expirations_set
        if date.fromisoformat(exp) > as_of
    )
    if not future_exps:
        return []

    months = sorted({
        (date.fromisoformat(exp).year, date.fromisoformat(exp).month)
        for exp in future_exps
    })

    results: list[str] = []
    for year, month in months:
        monthly_exp = _standard_monthly_expiration(year, month, expirations_set)
        if monthly_exp and monthly_exp not in results and date.fromisoformat(monthly_exp) > as_of:
            results.append(monthly_exp)

    return results


def nearest_strike(strikes: pd.Series | list, target: float) -> float:
    """Choose the listed strike closest to target (ties: lower strike)."""
    s = pd.Series(strikes, dtype=float).dropna()
    if s.empty:
        raise ValueError("Empty strike list")
    diff = (s - target).abs()
    min_d = diff.min()
    return float(s.loc[diff == min_d].min())


def leg_mid_from_chain(chain_df: pd.DataFrame, strike: float, right: Right) -> float:
    """
    Get a best-effort mid price for one (strike, right) from a yfinance chain DataFrame.

    Priority:
    - (bid+ask)/2 when both are finite and > 0
    - lastPrice when finite and > 0
    """
    df = chain_df
    if "right" in df.columns:
        m = (df["right"].astype(str).str.upper() == right) & (pd.to_numeric(df["strike"], errors="coerce") == float(strike))
    else:
        # fall back: infer right if the caller passed raw calls/puts frames
        m = pd.to_numeric(df["strike"], errors="coerce") == float(strike)

    row = df.loc[m].head(1)
    if row.empty:
        raise RuntimeError(f"No contract found in chain for strike={strike} right={right}")
    r = row.iloc[0]

    bid = pd.to_numeric(r.get("bid", pd.NA), errors="coerce")
    ask = pd.to_numeric(r.get("ask", pd.NA), errors="coerce")
    if pd.notna(bid) and pd.notna(ask) and float(bid) > 0 and float(ask) > 0:
        return float((float(bid) + float(ask)) / 2.0)

    last = pd.to_numeric(r.get("lastPrice", pd.NA), errors="coerce")
    if pd.notna(last) and float(last) > 0:
        return float(last)

    raise RuntimeError(f"No usable price for strike={strike} right={right} (bid={bid}, ask={ask}, lastPrice={last})")


class YFinanceClient:
    """
    Drop-in-ish data client for the screener using yfinance (delayed/polling).
    """

    def connect(self, *_: object, **__: object) -> None:  # pragma: no cover
        return

    def disconnect(self) -> None:  # pragma: no cover
        return

    def qualify_stock(self, symbol: str) -> str:
        return symbol.upper().strip()

    def get_technical_indicators(self, symbol: str, sr_lookback: int = 60, atr_period: int = 14) -> TechnicalIndicators:
        return get_technical_indicators(symbol, sr_lookback, atr_period)

    def get_underlying_mid(self, stock: str, wait_seconds: float = 0.0) -> float:  # noqa: ARG002
        return float(get_stock_price(stock).price)

    def get_expirations(self, stock: str) -> pd.Series:
        return get_expirations(stock)

    def get_chain_df(self, stock: str, expiration: str) -> pd.DataFrame:
        return get_option_chain(stock, expiration)

    @staticmethod
    def nearest_monthly_expiration(expirations: pd.Series | list, as_of: Optional[date] = None) -> Optional[str]:
        return nearest_monthly_expiration(expirations, as_of=as_of)

    @staticmethod
    def monthly_expirations(expirations: pd.Series | list, as_of: Optional[date] = None) -> list[str]:
        return monthly_expirations(expirations, as_of=as_of)

    @staticmethod
    def nearest_strike(strikes: pd.Series | list, target: float) -> float:
        return nearest_strike(strikes, target)

    @staticmethod
    def leg_mid_from_chain(chain_df: pd.DataFrame, strike: float, right: Right) -> float:
        return leg_mid_from_chain(chain_df, strike, right)


def _pick_expiry(symbol: str, expiry: Optional[str]) -> str:
    t = yf.Ticker(symbol.upper().strip())
    exps = list(getattr(t, "options", []) or [])
    if not exps:
        raise RuntimeError(f"No option expirations returned for {symbol!r}")
    return expiry.strip() if expiry else exps[0]


def export_option_chain_csv(
    symbol: str,
    expiry: Optional[str] = None,
    out_dir: str | Path = ".",
) -> tuple[Path, Path, Path]:
    """
    Export calls, puts, and combined chain to CSV files.

    Returns (calls_path, puts_path, combined_path).
    """
    sym = symbol.upper().strip()
    exp = _pick_expiry(sym, expiry)
    t = yf.Ticker(sym)
    chain = t.option_chain(exp)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    calls_path = out_dir / f"{sym}_calls_{exp}.csv"
    puts_path = out_dir / f"{sym}_puts_{exp}.csv"
    combined_path = out_dir / f"{sym}_chain_{exp}.csv"

    chain.calls.to_csv(calls_path, index=False)
    chain.puts.to_csv(puts_path, index=False)
    get_option_chain(sym, exp).to_csv(combined_path, index=False)
    return calls_path, puts_path, combined_path


def _csv_preview(path: Path, n: int = 10) -> str:
    df = pd.read_csv(path)
    return df.head(n).to_csv(index=False).rstrip()


if __name__ == "__main__":
    # Example usage:
    #   python -m ibkr_IC.iron_screener.yfinance_client AAPL 2026-05-15
    import sys

    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    expiry = sys.argv[2] if len(sys.argv) > 2 else None

    sp = get_stock_price(symbol)
    print(f"Underlying {sp.symbol} price: {sp.price} (as_of={sp.as_of})")

    calls_csv, puts_csv, combined_csv = export_option_chain_csv(
        symbol=symbol,
        expiry=expiry,
        out_dir=Path.cwd(),
    )

    print("\nCalls CSV preview:")
    print(_csv_preview(calls_csv, n=10))

    print("\nPuts CSV preview:")
    print(_csv_preview(puts_csv, n=10))

    print("\nCombined CSV preview:")
    print(_csv_preview(combined_csv, n=10))
