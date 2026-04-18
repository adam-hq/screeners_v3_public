"""
Yahoo Finance (yfinance) helpers for delayed underlying + option chain data.

This is intended as a lightweight alternative data source to IBKR/TWS for
screening workflows where delayed quotes are acceptable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional, Tuple

import pandas as pd
import yfinance as yf


Right = Literal["C", "P"]


@dataclass(frozen=True)
class StockPrice:
    symbol: str
    price: float
    as_of: Optional[datetime] = None
    source: str = "yfinance"


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


def nearest_monthly_expiration(
    expirations: pd.Series | list,
    as_of: Optional[date] = None,
) -> Optional[str]:
    """
    Pick the nearest future expiration whose date is the 3rd Friday (standard monthly).

    If none match, return the earliest future expiration string.
    """
    as_of = as_of or date.today()
    exp_s = pd.Series(expirations, dtype="string").dropna()
    if exp_s.empty:
        return None

    rows = []
    for exp in exp_s.astype(str).str.strip():
        try:
            d = datetime.strptime(exp, "%Y-%m-%d").date()
        except ValueError:
            # yfinance expirations are typically YYYY-MM-DD; ignore anything else
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
