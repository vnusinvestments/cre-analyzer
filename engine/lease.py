"""
Lease schedule builder.

Builds an annual rent schedule using real calendar dates; partial years
are prorated by actual days.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, List, Dict


@dataclass
class LeaseYear:
    year_num: int          # 1-indexed analysis year
    start: date
    end: date              # inclusive last day
    rent: float            # prorated annual rent for this analysis year
    term_type: str         # 'primary', 'option_1', ..., 'vacant'
    days_total: int
    days_primary: int
    days_option: int
    days_vacant: int


def _add_years(d: date, n: int) -> date:
    """Add n calendar years, clamping Feb 29 to Feb 28 in non-leap years."""
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def _complete_years_between(d1: date, d2: date) -> int:
    """Number of full calendar years from d1 through d2."""
    years = d2.year - d1.year
    if (d2.month, d2.day) < (d1.month, d1.day):
        years -= 1
    return max(0, years)


def _build_term_periods(
    lease_start: date,
    lease_expiration: date,
    renewal_options: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    Timeline of non-overlapping periods covering the lease life.
    Assumes the tenant exercises every renewal option.
    Each dict has keys: start, end (inclusive), type.
    """
    periods: List[Dict] = [
        {"start": lease_start, "end": lease_expiration, "type": "primary"}
    ]

    if renewal_options:
        current_start = lease_expiration + timedelta(days=1)
        option_num = 1
        for opt in renewal_options:
            count = opt.get("count", 1)
            years_each = opt.get("years_each", 5)
            for _ in range(count):
                current_end = _add_years(current_start, years_each) - timedelta(days=1)
                periods.append(
                    {
                        "start": current_start,
                        "end": current_end,
                        "type": f"option_{option_num}",
                        "option_num": option_num,
                        "opt_data": opt,
                    }
                )
                current_start = current_end + timedelta(days=1)
                option_num += 1

    return periods


def _primary_annual_rent_at(
    d: date,
    base_annual_rent: float,
    lease_start: date,
    escalation_type: str,
    escalation_pct: float,
    escalation_years: int,
    fixed_steps: Optional[List[Dict]],
) -> float:
    """Annual rent rate in effect on date d (within the primary term)."""
    if escalation_type == "flat":
        return base_annual_rent

    if escalation_type == "percent":
        years_elapsed = _complete_years_between(lease_start, d)
        num_increases = years_elapsed // escalation_years
        return base_annual_rent * (1 + escalation_pct) ** num_increases

    if escalation_type == "fixed_steps":
        rent = base_annual_rent
        if fixed_steps:
            for step in sorted(fixed_steps, key=lambda s: s["date"]):
                if d >= step["date"]:
                    rent = step["new_rent"]
                else:
                    break
        return rent

    return base_annual_rent


def _primary_rent_for_range(
    seg_start: date,
    seg_end: date,
    base_annual_rent: float,
    lease_start: date,
    escalation_type: str,
    escalation_pct: float,
    escalation_years: int,
    fixed_steps: Optional[List[Dict]],
    year_total_days: int = 365,
) -> float:
    """
    Prorated rent contribution for a contiguous segment of the primary term.

    Uses year_total_days (actual days in the analysis year) as the denominator
    so a full year at $X/yr always contributes exactly $X regardless of leap years.
    Handles intra-segment escalation boundaries for percent / fixed_steps leases.
    """
    if escalation_type == "flat":
        days = (seg_end - seg_start).days + 1
        return base_annual_rent * days / year_total_days

    # Walk forward through escalation boundaries within [seg_start, seg_end]
    total = 0.0
    cursor = seg_start
    while cursor <= seg_end:
        if escalation_type == "percent":
            yr_elapsed = _complete_years_between(lease_start, cursor)
            cur_incr = yr_elapsed // escalation_years
            annual_rate = base_annual_rent * (1 + escalation_pct) ** cur_incr
            # Next escalation date
            next_esc = _add_years(lease_start, (cur_incr + 1) * escalation_years)
        elif escalation_type == "fixed_steps":
            annual_rate = _primary_annual_rent_at(
                cursor, base_annual_rent, lease_start, escalation_type,
                escalation_pct, escalation_years, fixed_steps,
            )
            # Next step date after cursor
            next_esc = seg_end + timedelta(days=1)  # default: no more steps
            if fixed_steps:
                for step in sorted(fixed_steps, key=lambda s: s["date"]):
                    if step["date"] > cursor:
                        next_esc = step["date"]
                        break
        else:
            annual_rate = base_annual_rent
            next_esc = seg_end + timedelta(days=1)

        chunk_end = min(seg_end, next_esc - timedelta(days=1))
        days = (chunk_end - cursor).days + 1
        total += annual_rate * days / year_total_days
        cursor = chunk_end + timedelta(days=1)

    return total


def _option_annual_rent(
    opt_num: int,
    opt_data: Dict,
    base_annual_rent: float,
    lease_start: date,
    lease_expiration: date,
    escalation_type: str,
    escalation_pct: float,
    escalation_years: int,
    fixed_steps: Optional[List[Dict]],
    term_periods: List[Dict],
) -> float:
    """Annual rent for an option period (flat during the option)."""
    if opt_data.get("fixed_rent"):
        return float(opt_data["fixed_rent"])

    # Rent at end of primary term (last escalation point)
    rent_at_expiry = _primary_annual_rent_at(
        lease_expiration, base_annual_rent, lease_start,
        escalation_type, escalation_pct, escalation_years, fixed_steps,
    )
    change_pct = opt_data.get("rent_change_pct", 0.0)

    if opt_num == 1:
        return rent_at_expiry * (1 + change_pct)

    # Chain through previous options
    prev_rent = rent_at_expiry
    for period in term_periods:
        if not period["type"].startswith("option_"):
            continue
        p_num = int(period["type"].split("_")[1])
        if p_num < opt_num:
            p_opt = period.get("opt_data", {})
            p_change = p_opt.get("rent_change_pct", 0.0)
            prev_rent = prev_rent * (1 + p_change)
        elif p_num == opt_num:
            break

    return prev_rent * (1 + change_pct)


def build_rent_schedule(
    base_annual_rent: float,
    lease_start: date,
    lease_expiration: date,
    escalation_type: str = "flat",
    escalation_pct: float = 0.0,
    escalation_years: int = 5,
    fixed_steps: Optional[List[Dict]] = None,
    renewal_options: Optional[List[Dict]] = None,
    analysis_start: Optional[date] = None,
    hold_years: int = 10,
) -> List[LeaseYear]:
    """
    Build annual rent schedule for hold_years + 1 periods.

    The extra period (year hold_years + 1) gives the following-year NOI
    used to compute the reversion / exit value.

    Each year runs from analysis_start + (year-1) years to
    analysis_start + year years − 1 day.

    renewal_options is a list of dicts with keys:
        count          (int)   number of separate option periods
        years_each     (int)   length of each option in years
        rent_change_pct (float) % change at start of option (0 = flat)
        fixed_rent     (float) fixed annual rent amount (overrides rent_change_pct)
    """
    if analysis_start is None:
        analysis_start = lease_start

    term_periods = _build_term_periods(lease_start, lease_expiration, renewal_options)

    # Pre-compute option rents (flat per option period)
    option_rents: Dict[str, float] = {}
    for period in term_periods:
        if period["type"].startswith("option_"):
            opt_num = int(period["type"].split("_")[1])
            option_rents[period["type"]] = _option_annual_rent(
                opt_num, period.get("opt_data", {}),
                base_annual_rent, lease_start, lease_expiration,
                escalation_type, escalation_pct, escalation_years, fixed_steps,
                term_periods,
            )

    rows: List[LeaseYear] = []
    for yr in range(1, hold_years + 2):  # +1 for exit-year NOI
        yr_start = _add_years(analysis_start, yr - 1)
        yr_end = _add_years(analysis_start, yr) - timedelta(days=1)
        total_days = (yr_end - yr_start).days + 1

        rent_total = 0.0
        days_primary = 0
        days_option = 0
        days_vacant = 0
        type_days: Dict[str, int] = {}

        for period in term_periods:
            ol_start = max(yr_start, period["start"])
            ol_end = min(yr_end, period["end"])
            if ol_start > ol_end:
                continue
            days = (ol_end - ol_start).days + 1
            ptype = period["type"]
            type_days[ptype] = type_days.get(ptype, 0) + days

            if ptype == "primary":
                rent_total += _primary_rent_for_range(
                    ol_start, ol_end, base_annual_rent, lease_start,
                    escalation_type, escalation_pct, escalation_years, fixed_steps,
                    year_total_days=total_days,
                )
            elif ptype.startswith("option_"):
                annual_rate = option_rents[ptype]
                rent_total += annual_rate * days / total_days

        covered = sum(type_days.values())
        days_vacant = total_days - covered

        days_primary = type_days.get("primary", 0)
        days_option = sum(v for k, v in type_days.items() if k.startswith("option_"))

        # Dominant term type for display
        if type_days:
            dominant = max(type_days, key=type_days.get)
        elif days_vacant > 0:
            dominant = "vacant"
        else:
            dominant = "vacant"

        rows.append(
            LeaseYear(
                year_num=yr,
                start=yr_start,
                end=yr_end,
                rent=rent_total,
                term_type=dominant,
                days_total=total_days,
                days_primary=days_primary,
                days_option=days_option,
                days_vacant=days_vacant,
            )
        )

    return rows
