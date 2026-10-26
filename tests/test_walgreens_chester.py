"""
Verification test: Walgreens Chester

Inputs
------
Price               $3,840,000
Base rent           $240,000/yr flat
Lease type          Absolute NNN
Lease start         2005-10-08
Lease expiration    2037-05-31
Renewal options     8 × 5-year (flat rent, no change)
Analysis start      2026-11-01
Hold period         10 years
Closing costs       0%
Sale costs          0%
Exit cap rate       8.00%
Loan LTV            65%
Loan rate           7.00%
Amortization        25 years
IO months           0
Loan fees           0%

Expected values (tolerance ±0.5% relative, or ±$1 for amounts under $10)
-------------------------------------------------------------------------
Going-in cap rate   6.25%
Price at 8.00%      $3,000,000
Price at 8.50%      $2,823,529
Price at 9.00%      $2,666,667
Loan amount         $2,496,000
Monthly payment     $17,641.21
Annual DS           $211,694.51
DSCR                1.134
Yr-1 CoC CF         $28,305.49
Yr-1 CoC            2.11%
Loan balance yr 10  $1,962,689.57
Unlevered IRR       4.47%
Levered IRR         −0.20%
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date
from engine.lease import build_rent_schedule
from engine.cashflow import calc_cashflow
from engine.valuation import going_in_cap_rate, price_from_cap, price_ladder
from engine.debt import calc_debt
from engine.returns import calc_returns


# ── Tolerances ───────────────────────────────────────────────────────────────

def rel(actual, expected, pct=0.005):
    """±0.5% relative."""
    assert expected != 0, "expected must be non-zero"
    return abs(actual - expected) / abs(expected) <= pct


def abs_tol(actual, expected, tol=1.0):
    """Absolute tolerance (default ±$1)."""
    return abs(actual - expected) <= tol


def pct_pts(actual, expected, tol=0.001):
    """Percentage-point tolerance (e.g. ±0.1 pp for IRR)."""
    return abs(actual - expected) <= tol


# ── Shared fixture ────────────────────────────────────────────────────────────

PRICE = 3_840_000.0
BASE_RENT = 240_000.0
LEASE_START = date(2005, 10, 8)
LEASE_EXPIRATION = date(2037, 5, 31)
ANALYSIS_START = date(2026, 11, 1)
HOLD_YEARS = 10
EXIT_CAP = 0.08
LTV = 0.65
RATE = 0.07
AMORT_YEARS = 25

RENEWAL_OPTIONS = [{"count": 8, "years_each": 5, "rent_change_pct": 0.0}]


def _build_all():
    lease_rows = build_rent_schedule(
        base_annual_rent=BASE_RENT,
        lease_start=LEASE_START,
        lease_expiration=LEASE_EXPIRATION,
        escalation_type="flat",
        renewal_options=RENEWAL_OPTIONS,
        analysis_start=ANALYSIS_START,
        hold_years=HOLD_YEARS,
    )
    cashflows = calc_cashflow(
        lease_rows=lease_rows,
        lease_type="absolute_nnn",
        hold_years=HOLD_YEARS,
    )
    debt = calc_debt(
        price=PRICE,
        ltv=LTV,
        rate=RATE,
        amort_years=AMORT_YEARS,
        io_months=0,
        loan_fee_pct=0.0,
        hold_years=HOLD_YEARS,
        noi_yr1=cashflows[0]["noi"],
    )
    noi_yr1 = cashflows[0]["noi"]
    exit_noi = cashflows[HOLD_YEARS]["noi"]   # year 11 row
    ret = calc_returns(
        price=PRICE,
        closing_costs_pct=0.0,
        loan=debt["loan"],
        loan_fees=debt["loan_fees"],
        annual_ds=debt["annual_ds"],
        cashflows=cashflows,
        exit_noi=exit_noi,
        exit_cap=EXIT_CAP,
        sale_costs_pct=0.0,
        debt_schedule=debt["schedule"],
        hold_years=HOLD_YEARS,
    )
    return lease_rows, cashflows, debt, ret


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_rent_schedule_years_1_to_10():
    """All 10 analysis years should be in the primary term with rent = $240,000."""
    rows = build_rent_schedule(
        base_annual_rent=BASE_RENT,
        lease_start=LEASE_START,
        lease_expiration=LEASE_EXPIRATION,
        escalation_type="flat",
        renewal_options=RENEWAL_OPTIONS,
        analysis_start=ANALYSIS_START,
        hold_years=HOLD_YEARS,
    )
    for r in rows[:HOLD_YEARS]:
        assert abs(r.rent - BASE_RENT) < 1.0, (
            f"Year {r.year_num}: expected rent ${BASE_RENT:,.2f}, got ${r.rent:,.2f}"
        )
        assert r.term_type == "primary", (
            f"Year {r.year_num}: expected 'primary', got '{r.term_type}'"
        )


def test_going_in_cap_rate():
    _, cashflows, _, _ = _build_all()
    noi = cashflows[0]["noi"]
    cap = going_in_cap_rate(noi, PRICE)
    assert rel(cap, 0.0625), f"Going-in cap: expected 6.25%, got {cap*100:.4f}%"


def test_price_ladder():
    _, cashflows, _, _ = _build_all()
    noi = cashflows[0]["noi"]
    ladder = {row["cap_rate"]: row["price"] for row in price_ladder(noi)}

    assert rel(ladder[0.08], 3_000_000), (
        f"Price at 8.00%: expected $3,000,000, got ${ladder[0.08]:,.2f}"
    )
    assert rel(ladder[0.085], 2_823_529), (
        f"Price at 8.50%: expected $2,823,529, got ${ladder[0.085]:,.2f}"
    )
    assert rel(ladder[0.09], 2_666_667), (
        f"Price at 9.00%: expected $2,666,667, got ${ladder[0.09]:,.2f}"
    )


def test_loan_amount():
    _, _, debt, _ = _build_all()
    assert rel(debt["loan"], 2_496_000), (
        f"Loan: expected $2,496,000, got ${debt['loan']:,.2f}"
    )


def test_monthly_payment():
    _, _, debt, _ = _build_all()
    assert rel(debt["monthly_pmt"], 17_641.21), (
        f"Monthly pmt: expected $17,641.21, got ${debt['monthly_pmt']:,.2f}"
    )


def test_annual_debt_service():
    _, _, debt, _ = _build_all()
    assert rel(debt["annual_ds"], 211_694.51), (
        f"Annual DS: expected $211,694.51, got ${debt['annual_ds']:,.2f}"
    )


def test_dscr():
    _, _, debt, _ = _build_all()
    assert rel(debt["dscr"], 1.134), (
        f"DSCR: expected 1.134, got {debt['dscr']:.4f}"
    )


def test_yr1_coc_cashflow():
    _, cashflows, debt, ret = _build_all()
    yr1_cf = cashflows[0]["net_cf"] - debt["schedule"][0]["annual_ds"]
    assert rel(yr1_cf, 28_305.49), (
        f"Yr-1 CoC CF: expected $28,305.49, got ${yr1_cf:,.2f}"
    )


def test_yr1_coc():
    _, cashflows, debt, ret = _build_all()
    coc = ret["coc_by_year"][0]["coc"]
    assert rel(coc, 0.0211), (
        f"Yr-1 CoC: expected 2.11%, got {coc*100:.4f}%"
    )


def test_loan_balance_year_10():
    _, _, debt, _ = _build_all()
    bal = debt["schedule"][9]["end_balance"]
    assert rel(bal, 1_962_689.57), (
        f"Loan balance yr 10: expected $1,962,689.57, got ${bal:,.2f}"
    )


def test_unlevered_irr():
    _, _, _, ret = _build_all()
    irr = ret["unlevered_irr"]
    assert irr is not None, "Unlevered IRR is None"
    assert rel(irr, 0.0447), (
        f"Unlevered IRR: expected 4.47%, got {irr*100:.4f}%"
    )


def test_levered_irr():
    _, _, _, ret = _build_all()
    irr = ret["levered_irr"]
    assert irr is not None, "Levered IRR is None"
    # Near zero: use absolute ±0.2pp tolerance
    expected = -0.0020
    assert abs(irr - expected) <= 0.002, (
        f"Levered IRR: expected ~−0.20%, got {irr*100:.4f}%"
    )
