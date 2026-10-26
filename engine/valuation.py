"""
Valuation: direct cap, price ladder, and DCF.
"""

import numpy_financial as npf
from typing import List, Dict, Optional


# ── Direct cap ──────────────────────────────────────────────────────────────

def going_in_cap_rate(noi: float, price: float) -> float:
    """Year-1 NOI ÷ purchase price."""
    if price == 0:
        return 0.0
    return noi / price


def price_from_cap(noi: float, cap_rate: float) -> float:
    """NOI ÷ cap rate."""
    if cap_rate == 0:
        return float("inf")
    return noi / cap_rate


# ── Price ladder ─────────────────────────────────────────────────────────────

def price_ladder(
    noi: float,
    low: float = 0.05,
    high: float = 0.10,
    step: float = 0.0025,
) -> List[Dict]:
    """
    Returns a list of {cap_rate, price} dicts from low to high inclusive.
    """
    rows = []
    cap = low
    while cap <= high + 1e-9:
        rows.append({"cap_rate": round(cap, 6), "price": price_from_cap(noi, cap)})
        cap += step
    return rows


# ── Exit proceeds ────────────────────────────────────────────────────────────

def exit_proceeds(
    noi_following_year: float,
    exit_cap: float,
    sale_costs_pct: float = 0.0,
) -> float:
    """
    Gross exit value = following-year NOI ÷ exit_cap.
    Net = gross × (1 − sale_costs_pct).
    """
    gross = price_from_cap(noi_following_year, exit_cap)
    return gross * (1.0 - sale_costs_pct)


# ── DCF (two-rate approach) ──────────────────────────────────────────────────

def dcf_value(
    cashflows: List[Dict],          # from calc_cashflow (hold_years entries)
    exit_noi: float,                # year hold+1 NOI for reversion
    exit_cap: float,
    sale_costs_pct: float = 0.0,
    in_lease_rate: float = 0.07,    # discount rate for in-lease cash flows
    post_lease_rate: float = 0.09,  # discount rate for post-lease + reversion
    lease_expiration=None,          # date; if None, all CFs use in_lease_rate
) -> Dict:
    """
    A.CRE two-rate STNL DCF:
    - Cash flows within the primary lease term are discounted at in_lease_rate
      (backed by the tenant's covenant).
    - Cash flows after the primary expiration are discounted at post_lease_rate
      (vacant / re-leasing risk).
    - Reversion (exit value) is discounted at post_lease_rate.

    Returns {'pv': float, 'exit_value': float}.
    """
    gross_exit = price_from_cap(exit_noi, exit_cap)
    net_exit = gross_exit * (1.0 - sale_costs_pct)

    hold_years = len(cashflows)
    pv = 0.0
    for cf in cashflows:
        t = cf["year_num"]
        noi = cf["net_cf"]
        if lease_expiration and cf["end"] > lease_expiration:
            r = post_lease_rate
        else:
            r = in_lease_rate
        pv += noi / (1.0 + r) ** t

    # Reversion discounted at post_lease_rate
    pv += net_exit / (1.0 + post_lease_rate) ** hold_years

    return {"pv": pv, "exit_value_gross": gross_exit, "exit_value_net": net_exit}
