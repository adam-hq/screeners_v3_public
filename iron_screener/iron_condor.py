"""
Iron condor representation and metric calculations for screening.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ib_insync import Option


@dataclass
class IronCondor:
    """
    Four-leg options structure (all same expiration):

    Strikes ascending: long_put < short_put < short_call < long_call

    - Long put (LP): protective wing below short put
    - Short put (SP): sold put
    - Short call (SC): sold call
    - Long call (LC): protective wing above short call
    """

    symbol: str
    expiration: str
    long_put: Option
    short_put: Option
    short_call: Option
    long_call: Option
    wing_width: float
    distance_pct: float

    @property
    def strikes_lp_sp_sc_lc(self) -> tuple[float, float, float, float]:
        return (
            float(self.long_put.strike),
            float(self.short_put.strike),
            float(self.short_call.strike),
            float(self.long_call.strike),
        )

    @staticmethod
    def net_credit(
        mid_lp: float,
        mid_sp: float,
        mid_sc: float,
        mid_lc: float,
    ) -> float:
        """
        Net credit received for opening the condor (positive = credit).

        Short legs add premium; long legs subtract.
        """
        return mid_sp + mid_sc - mid_lp - mid_lc

    @staticmethod
    def max_risk(wing_width: float, net_credit: float) -> float:
        """
        Approximate max loss per condor for equal-width put/call spreads:

        max_risk ≈ wing_width - net_credit (per user spec).
        """
        return wing_width - net_credit

    @staticmethod
    def risk_reward_ratio(net_credit: float, max_risk: float) -> Optional[float]:
        if max_risk <= 0:
            return None
        return net_credit / max_risk

    def metrics(
        self,
        mid_lp: float,
        mid_sp: float,
        mid_sc: float,
        mid_lc: float,
    ) -> tuple[float, float, Optional[float]]:
        """
        Return (net_credit, max_risk, risk_reward_ratio).

        risk_reward_ratio is None if max_risk <= 0 (invalid or degenerate structure).
        """
        credit = self.net_credit(mid_lp, mid_sp, mid_sc, mid_lc)
        risk = self.max_risk(self.wing_width, credit)
        rr = self.risk_reward_ratio(credit, risk)
        return credit, risk, rr
