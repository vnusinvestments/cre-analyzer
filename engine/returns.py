"""
Investment return metrics: IRR, equity multiple, cash-on-cash.
"""

import numpy_financial as npf
from typing import List, Dict


def calc_returns(
    price: float,
    closing_costs_pct: float,
    loan: float,
    loan_fees: float,
    annual_ds: float,
    cashflows: List[Dict],   # from calc_cashflow (hold_years rows)
    exit_noi: float,
    exit_cap: float,
    sale_costs_pct: float,
    debt_schedule: List[Dict],  # from calc_debt (hold_years rows)
    hold_years: int = 10,
    prelease_cost: float = 0.0,
) -> Dict:
    """
    Returns metrics for both unlevered and levered perspectives.

    Equity = price + closing_costs_$ + loan_fees − loan
    (closing_costs and loan_fees are acquisition-time cash outflows)

    Unlevered cash flows (property level, no debt):
        Year 0: −(price + closing_costs_$)
        Years 1..hold: net_cf (noi minus capital reserve)
        Year hold: add net exit proceeds

    Levered cash flows (equity level):
        Year 0: −equity
        Years 1..hold: net_cf − annual_ds
        Year hold: add (net_exit − remaining_loan_balance)
    """
    closing_costs = price * closing_costs_pct
    equity = price + closing_costs + loan_fees + prelease_cost - loan

    gross_exit = exit_noi / exit_cap if exit_cap else 0.0
    net_exit = gross_exit * (1.0 - sale_costs_pct)

    # ── Unlevered CFs ────────────────────────────────────────────────────────
    unlev_cfs = [-(price + closing_costs)]
    for cf in cashflows[:hold_years]:
        unlev_cfs.append(cf["net_cf"])
    # Replace last element: add exit proceeds
    unlev_cfs[-1] += net_exit

    unlev_irr_raw = npf.irr(unlev_cfs)
    unlevered_irr = float(unlev_irr_raw) if unlev_irr_raw is not None else None

    # ── Levered CFs ──────────────────────────────────────────────────────────
    lev_cfs = [-equity]
    final_loan_balance = 0.0
    for i, cf in enumerate(cashflows[:hold_years]):
        yr = cf["year_num"]
        ds = debt_schedule[i]["annual_ds"] if i < len(debt_schedule) else annual_ds
        after_ds = cf["net_cf"] - ds
        lev_cfs.append(after_ds)
        if i == hold_years - 1:
            final_loan_balance = debt_schedule[i]["end_balance"]

    # Replace last element: add equity reversion
    lev_cfs[-1] += net_exit - final_loan_balance

    lev_irr_raw = npf.irr(lev_cfs)
    levered_irr = float(lev_irr_raw) if lev_irr_raw is not None else None

    # ── CoC by year ──────────────────────────────────────────────────────────
    coc_by_year = []
    for i, cf in enumerate(cashflows[:hold_years]):
        yr = cf["year_num"]
        ds = debt_schedule[i]["annual_ds"] if i < len(debt_schedule) else annual_ds
        coc_cf = cf["net_cf"] - ds
        coc = coc_cf / equity if equity else 0.0
        coc_by_year.append({"year": yr, "coc_cf": coc_cf, "coc": coc})

    avg_coc = sum(r["coc"] for r in coc_by_year) / len(coc_by_year) if coc_by_year else 0.0

    # ── Equity multiple ───────────────────────────────────────────────────────
    total_equity_in = equity
    total_equity_out = sum(r["coc_cf"] for r in coc_by_year) + net_exit - final_loan_balance
    equity_multiple = (total_equity_in + total_equity_out) / total_equity_in if total_equity_in else 0.0

    total_profit = total_equity_out - total_equity_in

    return {
        "equity": equity,
        "gross_exit": gross_exit,
        "net_exit": net_exit,
        "final_loan_balance": final_loan_balance,
        "unlevered_irr": unlevered_irr,
        "levered_irr": levered_irr,
        "coc_by_year": coc_by_year,
        "avg_coc": avg_coc,
        "equity_multiple": equity_multiple,
        "total_profit": total_profit,
        "unlevered_cfs": unlev_cfs,
        "levered_cfs": lev_cfs,
    }
