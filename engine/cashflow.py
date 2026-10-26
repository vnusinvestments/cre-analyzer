"""
Annual cash flow (NOI) for the hold period.
"""

from typing import List, Dict, Optional
from engine.lease import LeaseYear
from engine.expenses import landlord_expenses


def calc_cashflow(
    lease_rows: List[LeaseYear],
    lease_type: str = "absolute_nnn",
    building_sf: float = 0.0,
    vacancy_loss_pct: float = 0.0,
    capital_reserve_per_sf: float = 0.0,
    roof_reserve_per_sf: float = 0.0,
    mgmt_pct: float = 0.0,
    non_recoverable: float = 0.0,
    hold_years: int = 10,
) -> List[Dict]:
    """
    Returns one dict per analysis year (length = hold_years + 1).

    The last entry (year hold_years + 1) is the following-year NOI used
    to compute the exit / reversion value.

    Each dict contains:
        year_num, start, end
        potential_gross_income  (rent from lease schedule)
        vacancy_loss
        effective_gross_income
        operating_expenses      (landlord-paid)
        noi                     (egi - opex)
        capital_reserve
        net_cf                  (noi - capital_reserve, before debt service)
    """
    rows = []
    for row in lease_rows[: hold_years + 1]:
        pgi = row.rent
        vac = pgi * vacancy_loss_pct
        egi = pgi - vac
        exp = landlord_expenses(
            lease_type=lease_type,
            building_sf=building_sf,
            roof_reserve_per_sf=roof_reserve_per_sf,
            mgmt_pct=mgmt_pct,
            non_recoverable=non_recoverable,
            gross_income=egi,
        )
        noi = egi - exp["total"]
        cap_res = building_sf * capital_reserve_per_sf
        rows.append(
            {
                "year_num": row.year_num,
                "start": row.start,
                "end": row.end,
                "potential_gross_income": pgi,
                "vacancy_loss": vac,
                "effective_gross_income": egi,
                "operating_expenses": exp["total"],
                "expense_breakdown": exp["breakdown"],
                "noi": noi,
                "capital_reserve": cap_res,
                "net_cf": noi - cap_res,
                "term_type": row.term_type,
            }
        )
    return rows
