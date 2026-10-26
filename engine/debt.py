"""
Loan amortization schedule.
"""

import numpy_financial as npf
from typing import List, Dict


def calc_debt(
    price: float,
    ltv: float,
    rate: float,            # annual interest rate (decimal, e.g. 0.07)
    amort_years: int,
    io_months: int = 0,
    loan_fee_pct: float = 0.0,
    hold_years: int = 10,
    noi_yr1: float = 0.0,
) -> Dict:
    """
    Returns a dict with scalar metrics and a per-year schedule.

    Keys: loan, monthly_pmt, annual_ds, dscr, debt_yield,
          loan_fees, schedule (list of annual rows)

    Each schedule row:
        year, beg_balance, interest, principal, end_balance, annual_ds
    """
    loan = price * ltv
    loan_fees = loan * loan_fee_pct
    monthly_rate = rate / 12.0
    amort_months = amort_years * 12

    # Fully-amortizing monthly payment (computed on original amortization term)
    monthly_pmt = -float(npf.pmt(monthly_rate, amort_months, loan))
    # During IO months the payment equals interest only
    io_pmt = loan * monthly_rate

    annual_ds_full = monthly_pmt * 12.0  # once full amortization begins

    dscr = noi_yr1 / annual_ds_full if annual_ds_full > 0 else 0.0
    debt_yield = noi_yr1 / loan if loan > 0 else 0.0

    # Build annual schedule
    schedule: List[Dict] = []
    balance = loan
    for yr in range(1, hold_years + 1):
        beg_balance = balance
        yr_interest = 0.0
        yr_principal = 0.0
        yr_ds = 0.0
        for mo in range(12):
            elapsed = (yr - 1) * 12 + mo  # 0-indexed months since origination
            interest = balance * monthly_rate
            if elapsed < io_months:
                principal = 0.0
                pmt = io_pmt
            else:
                principal = monthly_pmt - interest
                pmt = monthly_pmt
            yr_interest += interest
            yr_principal += principal
            yr_ds += pmt
            balance -= principal

        schedule.append(
            {
                "year": yr,
                "beg_balance": beg_balance,
                "interest": yr_interest,
                "principal": yr_principal,
                "end_balance": balance,
                "annual_ds": yr_ds,
            }
        )

    return {
        "loan": loan,
        "monthly_pmt": monthly_pmt,
        "annual_ds": annual_ds_full,
        "dscr": dscr,
        "debt_yield": debt_yield,
        "loan_fees": loan_fees,
        "schedule": schedule,
    }
