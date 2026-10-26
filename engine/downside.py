"""
Downside scenario: tenant goes dark.

The tenant vacates at a chosen analysis year.  The landlord receives zero rent
during the downtime but must pay taxes/insurance/CAM ($/SF).  After downtime a
new tenant moves in at a specified rent; TI and leasing commission are
one-time costs at lease commencement.
"""

import numpy_financial as npf
from typing import List, Dict, Optional


def calc_downside(
    base_cashflows: List[Dict],      # from calc_cashflow (hold_years rows, base case)
    price: float,
    closing_costs_pct: float,
    loan: float,
    loan_fees: float,
    debt_schedule: List[Dict],
    annual_ds: float,
    exit_cap: float,
    sale_costs_pct: float,
    building_sf: float,
    vacancy_start_year: int,         # analysis year tenant vacates (1-indexed)
    downtime_months: int = 12,
    downtime_costs_per_sf: float = 0.0,  # $/SF/yr landlord pays during vacancy
    re_lease_rent_per_sf: float = 0.0,   # $/SF/yr new tenant rent
    ti_per_sf: float = 0.0,
    lc_pct: float = 0.0,             # leasing commission % of first-year new rent
    hold_years: int = 10,
) -> Dict:
    """
    Returns a dict with downside cash flows, IRR, and DSCR by year,
    plus base-case comparisons.

    The downside scenario replaces base-case cash flows from vacancy_start_year
    onwards with:
      - Vacant years: 0 rent minus downtime carrying costs
      - Re-lease year: new rent minus TI and leasing commission (one-time)
      - Subsequent years: new NOI
    """
    closing_costs = price * closing_costs_pct
    equity = price + closing_costs + loan_fees - loan

    downtime_years = downtime_months / 12.0
    # Integer years of full vacancy + partial year flag
    full_vacant_years = int(downtime_years)
    partial_months = downtime_months % 12

    new_annual_rent = re_lease_rent_per_sf * building_sf
    new_yr1_lease_costs = (ti_per_sf + re_lease_rent_per_sf * lc_pct) * building_sf

    downside_cfs: List[Dict] = []
    for i, base_cf in enumerate(base_cashflows[:hold_years]):
        yr = base_cf["year_num"]
        if yr < vacancy_start_year:
            # Base case is unchanged
            downside_cfs.append({**base_cf, "scenario": "base"})
        else:
            offset = yr - vacancy_start_year  # 0 = first vacant year
            if offset < full_vacant_years:
                # Full year of vacancy: zero rent, landlord pays carrying costs
                carrying = building_sf * downtime_costs_per_sf
                noi_ds = -carrying
                downside_cfs.append({
                    **base_cf,
                    "noi": noi_ds,
                    "net_cf": noi_ds,
                    "scenario": "vacant",
                })
            elif offset == full_vacant_years and partial_months > 0:
                # Partial vacant + partial re-lease in same year
                frac_vacant = partial_months / 12.0
                frac_leased = 1.0 - frac_vacant
                carrying = building_sf * downtime_costs_per_sf * frac_vacant
                re_noi = new_annual_rent * frac_leased - new_yr1_lease_costs
                noi_ds = -carrying + re_noi
                downside_cfs.append({
                    **base_cf,
                    "noi": noi_ds,
                    "net_cf": noi_ds,
                    "scenario": "transition",
                })
            else:
                # Re-leased; first full year absorbs TI + LC if not yet done
                if offset == full_vacant_years and partial_months == 0:
                    noi_ds = new_annual_rent - new_yr1_lease_costs
                else:
                    noi_ds = new_annual_rent
                downside_cfs.append({
                    **base_cf,
                    "noi": noi_ds,
                    "net_cf": noi_ds,
                    "scenario": "re_leased",
                })

    # Exit NOI = last downside CF's NOI (approximation; ideally year hold+1)
    exit_noi_ds = downside_cfs[-1]["noi"] if downside_cfs else 0.0
    gross_exit = exit_noi_ds / exit_cap if exit_cap and exit_noi_ds > 0 else 0.0
    net_exit = gross_exit * (1.0 - sale_costs_pct)
    final_bal = debt_schedule[hold_years - 1]["end_balance"] if debt_schedule else 0.0

    # Unlevered downside CFs
    unlev_cfs = [-(price + closing_costs)]
    for cf in downside_cfs:
        unlev_cfs.append(cf["net_cf"])
    unlev_cfs[-1] += net_exit

    # Levered downside CFs
    lev_cfs = [-equity]
    for i, cf in enumerate(downside_cfs):
        ds = debt_schedule[i]["annual_ds"] if i < len(debt_schedule) else annual_ds
        lev_cfs.append(cf["net_cf"] - ds)
    lev_cfs[-1] += net_exit - final_bal

    unlev_irr_raw = npf.irr(unlev_cfs)
    lev_irr_raw = npf.irr(lev_cfs)

    dscr_by_year = []
    for i, cf in enumerate(downside_cfs):
        ds = debt_schedule[i]["annual_ds"] if i < len(debt_schedule) else annual_ds
        dscr = cf["noi"] / ds if ds else 0.0
        dscr_by_year.append({"year": cf["year_num"], "noi": cf["noi"], "ds": ds, "dscr": dscr})

    return {
        "downside_cashflows": downside_cfs,
        "unlevered_irr": float(unlev_irr_raw) if unlev_irr_raw is not None else None,
        "levered_irr": float(lev_irr_raw) if lev_irr_raw is not None else None,
        "dscr_by_year": dscr_by_year,
        "net_exit": net_exit,
        "final_loan_balance": final_bal,
    }
