"""
Two-way sensitivity grids.

Grid 1: purchase cap rate × exit cap rate → levered IRR
Grid 2: interest rate × LTV → Year-1 cash-on-cash and DSCR
"""

from typing import List, Dict
from engine.valuation import price_from_cap
from engine.debt import calc_debt
from engine.returns import calc_returns


def sensitivity_cap_rates(
    noi_yr1: float,
    cashflows: List[Dict],       # hold_years rows from calc_cashflow
    exit_noi: float,
    loan_ltv: float,
    loan_rate: float,
    loan_amort_years: int,
    loan_io_months: int = 0,
    loan_fee_pct: float = 0.0,
    closing_costs_pct: float = 0.0,
    sale_costs_pct: float = 0.0,
    hold_years: int = 10,
    purchase_caps: List[float] = None,
    exit_caps: List[float] = None,
) -> Dict:
    """
    Rows = purchase cap rates, columns = exit cap rates.
    Cell value = levered IRR (or None if IRR cannot be computed).
    """
    if purchase_caps is None:
        purchase_caps = [round(0.05 + i * 0.0025, 4) for i in range(21)]
    if exit_caps is None:
        exit_caps = [round(0.05 + i * 0.0025, 4) for i in range(21)]

    grid = []
    for pcap in purchase_caps:
        row = []
        price = price_from_cap(noi_yr1, pcap)
        debt = calc_debt(
            price, loan_ltv, loan_rate, loan_amort_years,
            io_months=loan_io_months, loan_fee_pct=loan_fee_pct,
            hold_years=hold_years, noi_yr1=noi_yr1,
        )
        for ecap in exit_caps:
            ret = calc_returns(
                price=price,
                closing_costs_pct=closing_costs_pct,
                loan=debt["loan"],
                loan_fees=debt["loan_fees"],
                annual_ds=debt["annual_ds"],
                cashflows=cashflows,
                exit_noi=exit_noi,
                exit_cap=ecap,
                sale_costs_pct=sale_costs_pct,
                debt_schedule=debt["schedule"],
                hold_years=hold_years,
            )
            row.append(ret["levered_irr"])
        grid.append(row)

    return {
        "purchase_caps": purchase_caps,
        "exit_caps": exit_caps,
        "grid": grid,  # grid[i][j] = IRR at purchase_caps[i], exit_caps[j]
    }


def sensitivity_debt(
    noi_yr1: float,
    price: float,
    cashflows: List[Dict],
    exit_noi: float,
    exit_cap: float,
    closing_costs_pct: float = 0.0,
    sale_costs_pct: float = 0.0,
    hold_years: int = 10,
    amort_years: int = 25,
    io_months: int = 0,
    rates: List[float] = None,
    ltvs: List[float] = None,
) -> Dict:
    """
    Rows = interest rates, columns = LTVs.
    Returns two grids: coc (Year-1 cash-on-cash) and dscr.
    """
    if rates is None:
        rates = [round(0.04 + i * 0.005, 4) for i in range(13)]  # 4% to 10%
    if ltvs is None:
        ltvs = [round(0.50 + i * 0.05, 2) for i in range(7)]   # 50% to 80%

    closing_costs = price * closing_costs_pct
    coc_grid = []
    dscr_grid = []

    for rate in rates:
        coc_row = []
        dscr_row = []
        for ltv in ltvs:
            debt = calc_debt(
                price, ltv, rate, amort_years,
                io_months=io_months, hold_years=hold_years, noi_yr1=noi_yr1,
            )
            equity = price + closing_costs + debt["loan_fees"] - debt["loan"]
            yr1_cf = cashflows[0]["net_cf"] if cashflows else 0.0
            yr1_after_ds = yr1_cf - debt["annual_ds"]
            coc = yr1_after_ds / equity if equity > 0 else None
            coc_row.append(coc)
            dscr_row.append(debt["dscr"])
        coc_grid.append(coc_row)
        dscr_grid.append(dscr_row)

    return {
        "rates": rates,
        "ltvs": ltvs,
        "coc_grid": coc_grid,
        "dscr_grid": dscr_grid,
    }
