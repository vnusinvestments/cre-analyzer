"""
Landlord expense calculation by lease type.

Lease types:
  absolute_nnn  Tenant pays everything; zero landlord expense.
  nnn           Tenant pays taxes, insurance, CAM; landlord may keep a
                roof/structure reserve and management fee.
  nn            Landlord pays roof/structure + management.
  gross         Landlord pays all operating expenses.
"""

LEASE_TYPES = ("absolute_nnn", "nnn", "nn", "gross")


def landlord_expenses(
    lease_type: str,
    building_sf: float = 0.0,
    roof_reserve_per_sf: float = 0.0,
    mgmt_pct: float = 0.0,
    non_recoverable: float = 0.0,
    gross_income: float = 0.0,
) -> dict:
    """
    Returns a dict with 'total' and an itemized 'breakdown'.

    Parameters
    ----------
    lease_type          One of LEASE_TYPES.
    building_sf         Rentable square footage.
    roof_reserve_per_sf Annual reserve for roof/structure ($/SF/yr); only for nnn, nn, gross.
    mgmt_pct            Management fee as fraction of gross income (e.g. 0.05 = 5%).
    non_recoverable     Other non-recoverable landlord expenses ($/yr).
    gross_income        Gross rental income for the period; used to calculate mgmt_pct.
    """
    if lease_type not in LEASE_TYPES:
        raise ValueError(f"lease_type must be one of {LEASE_TYPES}, got '{lease_type}'")

    if lease_type == "absolute_nnn":
        return {"total": 0.0, "breakdown": {"roof_reserve": 0.0, "mgmt": 0.0, "non_recoverable": 0.0}}

    roof = building_sf * roof_reserve_per_sf
    mgmt = gross_income * mgmt_pct
    other = non_recoverable

    return {
        "total": roof + mgmt + other,
        "breakdown": {
            "roof_reserve": roof,
            "mgmt": mgmt,
            "non_recoverable": other,
        },
    }
