"""
CRE Deal Analyzer — Streamlit UI
Phase 2: Pipeline, Deal Form, Analysis, Due Diligence, Notes
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
from datetime import date, datetime
from typing import Optional

from db.schema import init_db, STAGES, LEASE_TYPES, LEASE_TYPE_LABELS
from db.queries import (
    get_all_deals, get_deal, upsert_deal, delete_deal,
    get_scenarios, get_scenario, get_default_scenario,
    upsert_scenario, clone_scenario, delete_scenario,
    get_dd_items, ensure_dd_items, update_dd_item, add_dd_item, delete_dd_item,
    get_notes, add_note, delete_note,
)
from engine.lease import build_rent_schedule
from engine.cashflow import calc_cashflow
from engine.valuation import going_in_cap_rate, price_from_cap, price_ladder, exit_proceeds
from engine.debt import calc_debt
from engine.returns import calc_returns
from engine.sensitivity import sensitivity_cap_rates, sensitivity_debt
from engine.downside import calc_downside
from reports.pdf_report import build_pdf


# ── Constants ─────────────────────────────────────────────────────────────────

PROPERTY_TYPES = ["NNN Retail", "Office", "Industrial", "Medical", "Other"]
PAGES = ["Pipeline", "New / Edit Deal", "Analysis", "Due Diligence", "Notes"]
ESC_TYPES = {"flat": "Flat (no increases)", "percent": "% every N years", "fixed_steps": "Fixed steps (custom dates)"}


# ── Formatting ────────────────────────────────────────────────────────────────

def fm(v, decimals=0) -> str:
    """Format money."""
    if v is None:
        return "—"
    return f"${v:,.{decimals}f}"


def fp(v, decimals=2) -> str:
    """Format percentage."""
    if v is None:
        return "—"
    return f"{v * 100:.{decimals}f}%"


def fx(v, decimals=2) -> str:
    """Format multiplier."""
    if v is None:
        return "—"
    return f"{v:.{decimals}f}x"


def parse_date(s) -> Optional[date]:
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


# ── Engine runner ─────────────────────────────────────────────────────────────

def run_engine(scenario: dict, deal: dict) -> dict:
    """Run full analysis for a scenario. Returns {'error': ...} on failure."""
    required = {
        "price": "Purchase price",
        "lease_start": "Lease start",
        "lease_expiration": "Lease expiration",
    }
    missing = [label for key, label in required.items() if not scenario.get(key)]
    if scenario.get("base_annual_rent") is None:
        missing.append("Base annual rent")
    if missing:
        return {"error": f"Missing required inputs: {', '.join(missing)}"}

    try:
        lease_start = parse_date(scenario["lease_start"])
        lease_expiration = parse_date(scenario["lease_expiration"])
        analysis_start = parse_date(scenario.get("analysis_start")) or date.today()
        hold_years = int(scenario.get("hold_years") or 10)
        building_sf = float(deal.get("building_sf") or 0)
        price = float(scenario["price"])

        renewal_options = []
        rc = int(scenario.get("renewal_count") or 0)
        if rc > 0:
            renewal_options = [
                {
                    "count": rc,
                    "years_each": int(scenario.get("renewal_years") or 5),
                    "rent_change_pct": float(scenario.get("renewal_rent_pct") or 0.0),
                }
            ]

        lease_rows = build_rent_schedule(
            base_annual_rent=float(scenario["base_annual_rent"]),
            lease_start=lease_start,
            lease_expiration=lease_expiration,
            escalation_type=scenario.get("escalation_type") or "flat",
            escalation_pct=float(scenario.get("escalation_pct") or 0.0),
            escalation_years=int(scenario.get("escalation_years") or 5),
            renewal_options=renewal_options,
            analysis_start=analysis_start,
            hold_years=hold_years,
        )

        cashflows = calc_cashflow(
            lease_rows=lease_rows,
            lease_type=scenario.get("lease_type") or "absolute_nnn",
            building_sf=building_sf,
            vacancy_loss_pct=float(scenario.get("vacancy_loss_pct") or 0.0),
            capital_reserve_per_sf=float(scenario.get("capital_reserve_per_sf") or 0.0),
            roof_reserve_per_sf=float(scenario.get("roof_reserve_per_sf") or 0.0),
            mgmt_pct=float(scenario.get("mgmt_pct") or 0.0),
            non_recoverable=float(scenario.get("non_recoverable") or 0.0),
            hold_years=hold_years,
        )

        noi_yr1 = cashflows[0]["noi"]
        exit_cap = float(scenario.get("exit_cap") or 0.08)
        sale_costs_pct = float(scenario.get("sale_costs_pct") or 0.0)
        exit_noi = cashflows[hold_years]["noi"]

        debt = calc_debt(
            price=price,
            ltv=float(scenario.get("ltv") or 0.65),
            rate=float(scenario.get("rate") or 0.07),
            amort_years=int(scenario.get("amort_years") or 25),
            io_months=int(scenario.get("io_months") or 0),
            loan_fee_pct=float(scenario.get("loan_fee_pct") or 0.0),
            hold_years=hold_years,
            noi_yr1=noi_yr1,
        )

        ret = calc_returns(
            price=price,
            closing_costs_pct=float(scenario.get("closing_costs_pct") or 0.0),
            loan=debt["loan"],
            loan_fees=debt["loan_fees"],
            annual_ds=debt["annual_ds"],
            cashflows=cashflows,
            exit_noi=exit_noi,
            exit_cap=exit_cap,
            sale_costs_pct=sale_costs_pct,
            debt_schedule=debt["schedule"],
            hold_years=hold_years,
            prelease_cost=float(scenario.get("prelease_cost") or 0.0),
        )

        # Downside
        downside = None
        vs_yr = int(scenario.get("vacancy_start_year") or hold_years + 1)
        if 1 <= vs_yr <= hold_years:
            try:
                downside = calc_downside(
                    base_cashflows=cashflows[:hold_years],
                    price=price,
                    closing_costs_pct=float(scenario.get("closing_costs_pct") or 0.0),
                    loan=debt["loan"],
                    loan_fees=debt["loan_fees"],
                    debt_schedule=debt["schedule"],
                    annual_ds=debt["annual_ds"],
                    exit_cap=exit_cap,
                    sale_costs_pct=sale_costs_pct,
                    building_sf=building_sf,
                    vacancy_start_year=vs_yr,
                    downtime_months=int(scenario.get("downtime_months") or 12),
                    downtime_costs_per_sf=float(scenario.get("downtime_costs_per_sf") or 3.0),
                    re_lease_rent_per_sf=float(scenario.get("re_lease_rent_per_sf") or 0.0),
                    ti_per_sf=float(scenario.get("ti_per_sf") or 0.0),
                    lc_pct=float(scenario.get("lc_pct") or 0.05),
                    hold_years=hold_years,
                )
            except Exception:
                pass

        years_rem = max(0.0, (lease_expiration - analysis_start).days / 365.25)

        return {
            "lease_rows": lease_rows,
            "cashflows": cashflows[:hold_years],
            "exit_noi": exit_noi,
            "debt": debt,
            "ret": ret,
            "downside": downside,
            "years_remaining": years_rem,
            "noi_yr1": noi_yr1,
            "price": price,
            "building_sf": building_sf,
            "hold_years": hold_years,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _solve_price_for_irr(
    target_irr: float,
    cashflows: list,
    exit_noi: float,
    scenario: dict,
    hold_years: int,
) -> float:
    """Binary search: find purchase price that achieves target levered IRR."""
    lo, hi = 100_000.0, 200_000_000.0
    for _ in range(70):
        mid = (lo + hi) / 2.0
        d = calc_debt(
            mid,
            float(scenario.get("ltv") or 0.65),
            float(scenario.get("rate") or 0.07),
            int(scenario.get("amort_years") or 25),
            int(scenario.get("io_months") or 0),
            float(scenario.get("loan_fee_pct") or 0.0),
            hold_years=hold_years,
            noi_yr1=cashflows[0]["noi"],
        )
        r = calc_returns(
            mid,
            float(scenario.get("closing_costs_pct") or 0.0),
            d["loan"],
            d["loan_fees"],
            d["annual_ds"],
            cashflows,
            exit_noi,
            float(scenario.get("exit_cap") or 0.08),
            float(scenario.get("sale_costs_pct") or 0.0),
            d["schedule"],
            hold_years,
            float(scenario.get("prelease_cost") or 0.0),
        )
        lirr = r.get("levered_irr")
        if lirr is None:
            break
        if lirr > target_irr:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ── Page: Pipeline ────────────────────────────────────────────────────────────

def page_pipeline():
    st.header("Deal Pipeline")

    col_filter, col_new = st.columns([3, 1])
    with col_filter:
        stage_opts = ["All stages"] + STAGES
        sel_stage = st.selectbox("Filter by stage", stage_opts, label_visibility="collapsed")
    with col_new:
        if st.button("+ New deal", type="primary", use_container_width=True):
            st.session_state.deal_id = None
            st.session_state.scenario_id = None
            st.session_state.nav_pending = "New / Edit Deal"
            st.rerun()

    deals = get_all_deals()
    if sel_stage != "All stages":
        deals = [d for d in deals if d.get("stage") == sel_stage]

    if not deals:
        st.info("No deals yet — click **+ New deal** to add one.")
        return

    # Compute quick metrics from default scenario
    rows = []
    for d in deals:
        scen = get_default_scenario(d["id"])
        cap_rate = None
        irr = None
        if scen and scen.get("price") and scen.get("base_annual_rent") is not None:
            try:
                res = run_engine(scen, d)
                if "error" not in res:
                    cap_rate = res["ret"].get("levered_irr")  # borrowing field name below
                    cap_rate = going_in_cap_rate(res["noi_yr1"], res["price"])
                    irr = res["ret"].get("levered_irr")
            except Exception:
                pass
        rows.append(
            {
                "Name": d.get("name", ""),
                "Address": f"{d.get('city', '')}, {d.get('state', '')}".strip(", "),
                "Tenant": d.get("tenant") or "—",
                "Price": fm(scen.get("price") if scen else None),
                "Cap Rate": fp(cap_rate) if cap_rate else "—",
                "Levered IRR": fp(irr) if irr is not None else "—",
                "Stage": d.get("stage", "—"),
                "Updated": (d.get("updated_at") or "")[:10],
                "_id": d["id"],
            }
        )

    df = pd.DataFrame(rows).drop(columns=["_id"])
    st.dataframe(df, hide_index=True, use_container_width=True)

    st.markdown("---")
    st.subheader("Open a deal")
    deal_labels = [f"{d['name']}  ·  {d.get('tenant', '')}  ·  {d.get('stage', '')}" for d in deals]
    sel_idx = st.selectbox("Select deal", range(len(deal_labels)), format_func=lambda i: deal_labels[i],
                           label_visibility="collapsed")

    bc1, bc2 = st.columns(2)
    with bc1:
        if st.button("Open → Analysis", type="primary", use_container_width=True):
            d = deals[sel_idx]
            st.session_state.deal_id = d["id"]
            scens = get_scenarios(d["id"])
            if scens:
                st.session_state.scenario_id = scens[0]["id"]
            st.session_state.nav_pending = "Analysis"
            st.rerun()
    with bc2:
        if st.button("Edit deal", use_container_width=True):
            d = deals[sel_idx]
            st.session_state.deal_id = d["id"]
            scens = get_scenarios(d["id"])
            if scens:
                st.session_state.scenario_id = scens[0]["id"]
            st.session_state.nav_pending = "New / Edit Deal"
            st.rerun()


# ── Page: New / Edit Deal ─────────────────────────────────────────────────────

def page_deal_form():
    deal_id = st.session_state.get("deal_id")
    deal = get_deal(deal_id) if deal_id else {}
    scen_id = st.session_state.get("scenario_id")
    scen = get_scenario(scen_id) if scen_id else {}
    if not scen and deal_id:
        scen = get_default_scenario(deal_id) or {}

    title = "Edit Deal" if deal_id else "New Deal"
    st.header(title)

    tab_prop, tab_lease, tab_exp, tab_purch, tab_debt, tab_exit, tab_down = st.tabs(
        ["Property", "Lease", "Expenses", "Purchase", "Debt", "Exit", "Downside"]
    )

    with st.form("deal_form", clear_on_submit=False):
        # ── Property ─────────────────────────────────────────────────────────
        with tab_prop:
            st.subheader("Property")
            c1, c2 = st.columns(2)
            deal_name = c1.text_input("Deal name *", value=deal.get("name", ""),
                                      help="A short internal name for this deal (e.g. 'Walgreens Chester PA').")
            tenant = c2.text_input("Tenant *", value=deal.get("tenant", ""),
                                   help="The operating tenant name.")
            address = st.text_input("Address", value=deal.get("address", ""),
                                    help="Street address of the property.")
            c3, c4 = st.columns(2)
            city = c3.text_input("City", value=deal.get("city", ""))
            state = c4.text_input("State", value=deal.get("state", ""), max_chars=2)
            c5, c6, c7 = st.columns(3)
            prop_type = c5.selectbox("Property type", PROPERTY_TYPES,
                                     index=PROPERTY_TYPES.index(deal.get("property_type", "NNN Retail"))
                                     if deal.get("property_type") in PROPERTY_TYPES else 0)
            building_sf = c6.number_input("Building SF", min_value=0.0, value=float(deal.get("building_sf") or 0.0),
                                          step=500.0, format="%.0f",
                                          help="Rentable square footage.")
            land_acres = c7.number_input("Land acres", min_value=0.0, value=float(deal.get("land_acres") or 0.0),
                                         step=0.1, format="%.2f")
            c8, c9 = st.columns(2)
            year_built = c8.number_input("Year built", min_value=1800, max_value=2100,
                                         value=int(deal.get("year_built") or 2000), step=1)
            stage = c9.selectbox("Stage", STAGES,
                                 index=STAGES.index(deal.get("stage", "Screening"))
                                 if deal.get("stage") in STAGES else 0,
                                 help="Pipeline stage for this deal.")

        # ── Lease ─────────────────────────────────────────────────────────────
        with tab_lease:
            st.subheader("Lease")
            bsf_lease = float(deal.get("building_sf") or 0.0)
            stored_annual = float(scen.get("base_annual_rent") or 0.0)
            init_psf = round(stored_annual / bsf_lease, 2) if bsf_lease and stored_annual else 0.0

            lc1, lc2, lc3 = st.columns(3)
            rent_psf = lc1.number_input(
                "Rent ($/SF/yr)",
                min_value=0.0, value=init_psf,
                step=0.25, format="%.2f",
                help=f"Per square foot per year. Building: {bsf_lease:,.0f} SF.")
            if rent_psf > 0 and bsf_lease > 0:
                base_rent = rent_psf * bsf_lease
                lc1.caption(f"= ${base_rent:,.0f} / yr total")
            else:
                base_rent = lc2.number_input(
                    "Total annual rent ($) *", min_value=0.0,
                    value=stored_annual,
                    step=500.0, format="%.0f",
                    help="Total annual base rent. Use $/SF field above when building SF is set.")
            lease_type_sel = lc3.selectbox(
                "Lease type *",
                list(LEASE_TYPE_LABELS.keys()),
                format_func=lambda k: LEASE_TYPE_LABELS[k],
                index=list(LEASE_TYPE_LABELS.keys()).index(scen.get("lease_type") or "absolute_nnn"),
                help="Determines who pays operating expenses. Absolute NNN = tenant pays everything.")

            lc3, lc4 = st.columns(2)
            lease_start_v = parse_date(scen.get("lease_start")) or date(2020, 1, 1)
            lease_exp_v = parse_date(scen.get("lease_expiration")) or date(2035, 1, 1)
            lease_start = lc3.date_input("Lease start *", value=lease_start_v,
                                         help="Date the primary term commences.")
            lease_exp = lc4.date_input("Lease expiration *", value=lease_exp_v,
                                       help="Last day of the primary term.")

            esc_type = st.selectbox(
                "Escalation type",
                list(ESC_TYPES.keys()),
                format_func=lambda k: ESC_TYPES[k],
                index=list(ESC_TYPES.keys()).index(scen.get("escalation_type") or "flat"),
                help="How rent changes over the lease term.")

            esc_pct, esc_yrs = 0.0, 5
            if esc_type == "percent":
                ec1, ec2 = st.columns(2)
                esc_pct = ec1.number_input("Escalation % per period", min_value=0.0, max_value=1.0,
                                           value=float(scen.get("escalation_pct") or 0.0),
                                           step=0.01, format="%.4f",
                                           help="E.g. 0.10 = rent increases 10% every N years.") or 0.0
                esc_yrs = int(ec2.number_input("Escalation every N years", min_value=1, max_value=30,
                                               value=int(scen.get("escalation_years") or 5), step=1))

            st.markdown("**Renewal options** — enter 0 count if none")
            rc1, rc2, rc3 = st.columns(3)
            ren_count = int(rc1.number_input("# of options", min_value=0, max_value=20,
                                             value=int(scen.get("renewal_count") or 0), step=1,
                                             help="Number of individual renewal option periods."))
            ren_yrs = int(rc2.number_input("Years per option", min_value=1, max_value=30,
                                           value=int(scen.get("renewal_years") or 5), step=1,
                                           help="Length of each option period in years."))
            ren_rent_pct = rc3.number_input(
                "Rent change at each option (%)", min_value=-1.0, max_value=1.0,
                value=float(scen.get("renewal_rent_pct") or 0.0),
                step=0.01, format="%.4f",
                help="0 = flat rent in options. 0.10 = 10% increase at each option.") or 0.0

        # ── Expenses ──────────────────────────────────────────────────────────
        with tab_exp:
            st.subheader("Expenses")
            ec1, ec2 = st.columns(2)
            vac_pct = ec1.number_input(
                "Vacancy / credit loss (%)", min_value=0.0, max_value=1.0,
                value=float(scen.get("vacancy_loss_pct") or 0.0),
                step=0.01, format="%.4f",
                help="% of rent lost to vacancy or tenant credit risk. Typically 0% for single-tenant net lease.") or 0.0
            cap_res = ec2.number_input(
                "Capital reserve ($/SF/yr)", min_value=0.0,
                value=float(scen.get("capital_reserve_per_sf") or 0.0),
                step=0.05, format="%.2f",
                help="Annual capital reserve for future capex, deducted from NOI.") or 0.0

            st.caption("Landlord expenses — only applicable for NNN, NN, and Gross leases")
            ee1, ee2, ee3 = st.columns(3)
            roof_res = ee1.number_input(
                "Roof/structure reserve ($/SF/yr)", min_value=0.0,
                value=float(scen.get("roof_reserve_per_sf") or 0.0),
                step=0.05, format="%.2f",
                help="Annual reserve for roof and structural repairs (landlord responsibility).") or 0.0
            mgmt_pct_v = ee2.number_input(
                "Management fee (%)", min_value=0.0, max_value=1.0,
                value=float(scen.get("mgmt_pct") or 0.0),
                step=0.01, format="%.4f",
                help="Property management fee as % of effective gross income.") or 0.0
            non_recov = ee3.number_input(
                "Non-recoverable expenses ($/yr)", min_value=0.0,
                value=float(scen.get("non_recoverable") or 0.0),
                step=100.0, format="%.0f",
                help="Other landlord expenses not reimbursed by the tenant.") or 0.0

        # ── Purchase ──────────────────────────────────────────────────────────
        with tab_purch:
            st.subheader("Purchase")
            pc1, pc2 = st.columns(2)
            price_v = pc1.number_input(
                "Purchase price ($) *", min_value=0.0,
                value=float(scen.get("price") or 0.0),
                step=10000.0, format="%.0f",
                help="Agreed purchase price (not including closing costs).") or None
            closing_pct = pc2.number_input(
                "Closing costs (%)", min_value=0.0, max_value=0.10,
                value=float(scen.get("closing_costs_pct") or 0.0),
                step=0.001, format="%.4f",
                help="Total acquisition closing costs as % of price (legal, title, transfer taxes, etc.).") or 0.0

            pc3, pc4 = st.columns(2)
            # Default analysis_start to lease_start when not previously set
            _lease_start_date = parse_date(scen.get("lease_start"))
            analysis_start_v = parse_date(scen.get("analysis_start")) or _lease_start_date or date.today()
            analysis_start = pc3.date_input(
                "Acquisition / close date",
                value=analysis_start_v,
                help="Expected close date. Set equal to lease start for a full Year 1; earlier dates model a pre-lease holding period.")
            hold_years_v = int(pc4.number_input(
                "Hold period (years)", min_value=1, max_value=20,
                value=int(scen.get("hold_years") or 10), step=1,
                help="Assumed holding period before sale."))

            pc5, pc6 = st.columns(2)
            prelease_cost_v = pc5.number_input(
                "Pre-lease renovation cost ($)",
                min_value=0.0,
                value=float(scen.get("prelease_cost") or 0.0),
                step=1000.0, format="%.0f",
                help="One-time costs between acquisition and lease start: renovation, carrying costs, etc. Added to equity invested.")
            if prelease_cost_v > 0 and _lease_start_date and _lease_start_date > analysis_start_v:
                gap_days = (_lease_start_date - analysis_start_v).days
                gap_months = round(gap_days / 30.4)
                pc5.caption(f"Pre-lease gap: ~{gap_months} months until lease starts {_lease_start_date.strftime('%b %d, %Y')}")

            scenario_name = st.text_input(
                "Scenario name", value=scen.get("name", "Asking"),
                help="Label for this set of assumptions, e.g. 'Asking', 'My offer', 'Best case'.")

        # ── Debt ──────────────────────────────────────────────────────────────
        with tab_debt:
            st.subheader("Debt")
            dc1, dc2, dc3 = st.columns(3)
            ltv = dc1.number_input(
                "LTV (%)", min_value=0.0, max_value=1.0,
                value=float(scen.get("ltv") or 0.65),
                step=0.01, format="%.4f",
                help="Loan-to-value ratio. E.g. 0.65 = 65% loan, 35% equity.") or 0.65
            rate = dc2.number_input(
                "Interest rate (%)", min_value=0.0, max_value=0.25,
                value=float(scen.get("rate") or 0.07),
                step=0.001, format="%.4f",
                help="Annual interest rate on the mortgage.") or 0.07
            amort_yrs = int(dc3.number_input(
                "Amortization (years)", min_value=1, max_value=40,
                value=int(scen.get("amort_years") or 25), step=1,
                help="Amortization term in years. 25 is common for NNN."))
            dc4, dc5 = st.columns(2)
            io_mo = int(dc4.number_input(
                "Interest-only months", min_value=0, max_value=120,
                value=int(scen.get("io_months") or 0), step=6,
                help="Months of interest-only payments before principal begins."))
            loan_fee = dc5.number_input(
                "Loan fee (%)", min_value=0.0, max_value=0.05,
                value=float(scen.get("loan_fee_pct") or 0.0),
                step=0.001, format="%.4f",
                help="Origination fee as % of loan amount (added to equity requirement).") or 0.0

        # ── Exit ──────────────────────────────────────────────────────────────
        with tab_exit:
            st.subheader("Exit / Reversion")
            ec1, ec2, ec3 = st.columns(3)
            exit_cap_v = ec1.number_input(
                "Exit cap rate (%)", min_value=0.01, max_value=0.30,
                value=float(scen.get("exit_cap") or 0.08),
                step=0.0025, format="%.4f",
                help="Cap rate applied to year-after-sale NOI to estimate exit price.") or 0.08
            sale_costs_v = ec2.number_input(
                "Sale costs (%)", min_value=0.0, max_value=0.10,
                value=float(scen.get("sale_costs_pct") or 0.0),
                step=0.001, format="%.4f",
                help="Broker commissions + closing costs at sale as % of gross exit value.") or 0.0
            target_irr_v = ec3.number_input(
                "Target levered IRR (%)", min_value=0.0, max_value=0.50,
                value=float(scen.get("target_irr") or 0.10),
                step=0.005, format="%.4f",
                help="Your minimum acceptable levered IRR. Used to color-code sensitivity grids.") or 0.10

        # ── Downside ──────────────────────────────────────────────────────────
        with tab_down:
            st.subheader("Downside — Tenant Goes Dark")
            st.caption("Model what happens if the tenant vacates at a chosen year.")
            da1, da2 = st.columns(2)
            vs_yr = int(da1.number_input(
                "Tenant vacates in year #", min_value=1, max_value=30,
                value=int(scen.get("vacancy_start_year") or (int(scen.get("hold_years") or 10) + 1)),
                step=1,
                help="Analysis year in which the tenant stops paying rent. Set > hold years to disable downside."))
            dt_mo = int(da2.number_input(
                "Downtime (months)", min_value=0, max_value=120,
                value=int(scen.get("downtime_months") or 12), step=3,
                help="Months of vacancy between the departing and new tenant."))
            da3, da4, da5 = st.columns(3)
            dt_costs = da3.number_input(
                "Carrying costs during vacancy ($/SF/yr)", min_value=0.0,
                value=float(scen.get("downtime_costs_per_sf") or 3.0),
                step=0.5, format="%.2f",
                help="Taxes, insurance, CAM the landlord pays while vacant.") or 0.0
            re_rent = da4.number_input(
                "Re-lease rent ($/SF/yr)", min_value=0.0,
                value=float(scen.get("re_lease_rent_per_sf") or 0.0),
                step=0.5, format="%.2f",
                help="New tenant's base rent per SF per year.") or 0.0
            ti_sf = da4.number_input(
                "TI allowance ($/SF)", min_value=0.0,
                value=float(scen.get("ti_per_sf") or 0.0),
                step=1.0, format="%.2f",
                help="Tenant improvement allowance paid by landlord at re-lease.") or 0.0
            lc = da5.number_input(
                "Leasing commission (%)", min_value=0.0, max_value=0.15,
                value=float(scen.get("lc_pct") or 0.05),
                step=0.005, format="%.4f",
                help="Leasing commission % of first year's new rent.") or 0.05

        # ── Submit ────────────────────────────────────────────────────────────
        submitted = st.form_submit_button("💾  Save deal", type="primary")

    if submitted:
        if not deal_name.strip():
            st.error("Deal name is required.")
            return

        deal_data = {
            "id": deal_id,
            "name": deal_name.strip(),
            "address": address,
            "city": city,
            "state": state,
            "tenant": tenant.strip(),
            "property_type": prop_type,
            "building_sf": building_sf,
            "land_acres": land_acres,
            "year_built": year_built,
            "stage": stage,
        }
        saved_deal_id = upsert_deal(deal_data)

        scen_data = {
            "id": scen_id if scen_id and deal_id else None,
            "deal_id": saved_deal_id,
            "name": scenario_name or "Asking",
            "is_default": 1,
            "base_annual_rent": base_rent or None,
            "lease_start": str(lease_start),
            "lease_expiration": str(lease_exp),
            "escalation_type": esc_type,
            "escalation_pct": esc_pct,
            "escalation_years": esc_yrs,
            "renewal_count": ren_count,
            "renewal_years": ren_yrs,
            "renewal_rent_pct": ren_rent_pct,
            "lease_type": lease_type_sel,
            "vacancy_loss_pct": vac_pct,
            "capital_reserve_per_sf": cap_res,
            "roof_reserve_per_sf": roof_res,
            "mgmt_pct": mgmt_pct_v,
            "non_recoverable": non_recov,
            "price": price_v or None,
            "closing_costs_pct": closing_pct,
            "analysis_start": str(analysis_start),
            "hold_years": hold_years_v,
            "prelease_cost": prelease_cost_v,
            "ltv": ltv,
            "rate": rate,
            "amort_years": amort_yrs,
            "io_months": io_mo,
            "loan_fee_pct": loan_fee,
            "exit_cap": exit_cap_v,
            "sale_costs_pct": sale_costs_v,
            "target_irr": target_irr_v,
            "vacancy_start_year": vs_yr,
            "downtime_months": dt_mo,
            "downtime_costs_per_sf": dt_costs,
            "re_lease_rent_per_sf": re_rent,
            "ti_per_sf": ti_sf,
            "lc_pct": lc,
        }
        saved_scen_id = upsert_scenario(scen_data)

        st.session_state.deal_id = saved_deal_id
        st.session_state.scenario_id = saved_scen_id
        st.success(f"Saved: {deal_name}")

        if not deal_id:
            ensure_dd_items(saved_deal_id)

    # Scenario management (outside the form)
    if deal_id:
        st.markdown("---")
        st.subheader("Scenarios")
        all_scens = get_scenarios(deal_id)
        if all_scens:
            for s in all_scens:
                sc1, sc2 = st.columns([4, 1])
                sc1.write(f"**{s['name']}**" + (" *(default)*" if s.get("is_default") else ""))
                if sc2.button("Clone →", key=f"clone_{s['id']}"):
                    new_name = f"{s['name']} (copy)"
                    new_id = clone_scenario(s["id"], new_name)
                    st.session_state.scenario_id = new_id
                    st.success(f"Created scenario: {new_name}")
                    st.rerun()
            if len(all_scens) > 1:
                del_scen_names = [s["name"] for s in all_scens]
                del_sel = st.selectbox("Delete scenario:", del_scen_names,
                                       label_visibility="visible", key="del_scen_sel")
                if st.button("Delete selected scenario", type="secondary"):
                    del_scen = next(s for s in all_scens if s["name"] == del_scen_names[del_scen_names.index(del_sel)])
                    delete_scenario(del_scen["id"])
                    remaining = [s for s in all_scens if s["id"] != del_scen["id"]]
                    st.session_state.scenario_id = remaining[0]["id"] if remaining else None
                    st.rerun()


# ── Page: Analysis ────────────────────────────────────────────────────────────

def page_analysis():
    deal_id = st.session_state.get("deal_id")
    if not deal_id:
        st.info("No deal open. Go to **Pipeline** and open a deal first.")
        return

    deal = get_deal(deal_id)
    if not deal:
        st.error("Deal not found.")
        return

    scen_id = st.session_state.get("scenario_id")
    scen = get_scenario(scen_id) if scen_id else None
    if not scen:
        scen = get_default_scenario(deal_id)
    if not scen:
        st.warning("No scenario found. Go to **New / Edit Deal** to add one.")
        return

    st.header(f"Analysis — {deal['name']}")
    st.caption(f"Scenario: **{scen.get('name', '—')}**  ·  Tenant: {deal.get('tenant', '—')}")

    res = run_engine(scen, deal)
    if "error" in res:
        st.error(f"Cannot compute: {res['error']}")
        return

    ret = res["ret"]
    debt = res["debt"]
    noi = res["noi_yr1"]
    price = res["price"]
    bsf = res["building_sf"]

    # ── Summary tiles ─────────────────────────────────────────────────────────
    st.markdown("### Summary")
    st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.05rem !important; white-space: nowrap; }
[data-testid="stMetricLabel"] { font-size: 0.72rem !important; }
</style>
""", unsafe_allow_html=True)
    t1, t2, t3, t4, t5, t6, t7, t8, t9, t10 = st.columns(10)
    t1.metric("Price", fm(price))
    _stab_noi = float(scen.get("base_annual_rent") or 0)
    t2.metric("Cap Rate", fp(going_in_cap_rate(_stab_noi, price)))
    t3.metric("NOI (Yr 1)", fm(noi))
    t4.metric("DSCR", f"{debt['dscr']:.2f}")
    t5.metric("CoC (Yr 1)", fp(ret["coc_by_year"][0]["coc"]))
    t6.metric("Levered IRR", fp(ret["levered_irr"]))
    t7.metric("Equity Multiple", fx(ret["equity_multiple"]))
    t8.metric("Price / SF", fm(price / bsf) if bsf else "—")
    _base_rent_sf = float(scen.get("base_annual_rent") or 0) / bsf if bsf else 0
    t9.metric("Rent / SF", f"${_base_rent_sf:.2f}" if bsf else "—")
    t10.metric("Yrs on Lease", f"{res['years_remaining']:.1f}")

    # ── Pre-lease info note ───────────────────────────────────────────────────
    _prelease_cost_disp = float(scen.get("prelease_cost") or 0.0)
    _analysis_start_disp = parse_date(scen.get("analysis_start")) or date.today()
    _lease_start_disp = parse_date(scen.get("lease_start"))
    if _lease_start_disp and _lease_start_disp > _analysis_start_disp:
        gap_days = (_lease_start_disp - _analysis_start_disp).days
        gap_months = round(gap_days / 30.4)
        _cost_note = f" | Renovation cost: **{fm(_prelease_cost_disp)}** included in equity" if _prelease_cost_disp > 0 else ""
        st.info(f"Pre-lease holding period: **{gap_months} months** (acquisition {_analysis_start_disp} → lease start {_lease_start_disp}){_cost_note}. Year 1 cash flow reflects partial year.")

    st.markdown("---")

    # ── Cash flow table ───────────────────────────────────────────────────────
    with st.expander("Annual Cash Flow", expanded=True):
        cf_rows = []
        for i, cf in enumerate(res["cashflows"]):
            ds = debt["schedule"][i]["annual_ds"]
            after_ds = cf["net_cf"] - ds
            cf_rows.append(
                {
                    "Year": cf["year_num"],
                    "Period": f"{cf['start']} → {cf['end']}",
                    "Rent": fm(cf["potential_gross_income"]),
                    "Vacancy": fm(-cf["vacancy_loss"]),
                    "OpEx": fm(-cf["operating_expenses"]),
                    "NOI": fm(cf["noi"]),
                    "Cap Res.": fm(-cf["capital_reserve"]),
                    "Net CF": fm(cf["net_cf"]),
                    "Debt Svc": fm(-ds),
                    "After DS": fm(after_ds),
                    "CoC": fp(ret["coc_by_year"][i]["coc"]),
                    "Term": cf["term_type"],
                }
            )
        # Add exit row
        cf_rows.append(
            {
                "Year": "Exit",
                "Period": "—",
                "Rent": "—",
                "Vacancy": "—",
                "OpEx": "—",
                "NOI": fm(res["exit_noi"]),
                "Cap Res.": "—",
                "Net CF": fm(ret["net_exit"]),
                "Debt Svc": fm(-ret["final_loan_balance"]),
                "After DS": fm(ret["net_exit"] - ret["final_loan_balance"]),
                "CoC": "—",
                "Term": "exit",
            }
        )
        st.dataframe(pd.DataFrame(cf_rows), hide_index=True, use_container_width=True)

    # ── Price ladder ──────────────────────────────────────────────────────────
    with st.expander("Price Ladder", expanded=True):
        ladder = price_ladder(noi)
        asking_cap = going_in_cap_rate(noi, price)
        pl_rows = []
        for row in ladder:
            pl_rows.append(
                {
                    "Cap Rate": fp(row["cap_rate"]),
                    "Implied Price": fm(row["price"]),
                    "vs. Asking": f"{'▲' if row['price'] > price else '▼'} {fm(abs(row['price'] - price))}",
                    "": "← Asking" if abs(row["cap_rate"] - asking_cap) < 0.00126 else "",
                }
            )
        pl_df = pd.DataFrame(pl_rows)
        # Highlight the asking-price row
        asking_idx = next(
            (i for i, r in enumerate(ladder) if abs(r["cap_rate"] - asking_cap) < 0.00126), None
        )

        def _highlight_asking(row):
            return ["background-color: #fff3cd; font-weight: bold"] * len(row) if row.name == asking_idx else [""] * len(row)

        st.dataframe(pl_df.style.apply(_highlight_asking, axis=1), hide_index=True, use_container_width=True)

    # ── Sensitivity: Cap Rate × Exit Cap → Levered IRR ───────────────────────
    target_irr = float(scen.get("target_irr") or 0.10)
    with st.expander("Sensitivity: Purchase Cap Rate × Exit Cap Rate → Levered IRR", expanded=True):
        col_tgt = st.columns([1, 3])[0]
        target_irr_disp = col_tgt.number_input(
            "Target IRR for coloring (%)",
            min_value=0.0, max_value=0.50,
            value=target_irr,
            step=0.005, format="%.3f",
            key="sens1_target",
        )
        p_caps = [round(0.055 + i * 0.005, 4) for i in range(15)]  # 5.5%–12.5%
        e_caps = [round(0.060 + i * 0.005, 4) for i in range(11)]  # 6.0%–11.0%
        sg = sensitivity_cap_rates(
            noi_yr1=noi,
            cashflows=res["cashflows"],
            exit_noi=res["exit_noi"],
            loan_ltv=float(scen.get("ltv") or 0.65),
            loan_rate=float(scen.get("rate") or 0.07),
            loan_amort_years=int(scen.get("amort_years") or 25),
            loan_io_months=int(scen.get("io_months") or 0),
            loan_fee_pct=float(scen.get("loan_fee_pct") or 0.0),
            closing_costs_pct=float(scen.get("closing_costs_pct") or 0.0),
            sale_costs_pct=float(scen.get("sale_costs_pct") or 0.0),
            hold_years=res["hold_years"],
            purchase_caps=p_caps,
            exit_caps=e_caps,
        )
        irr_grid_df = pd.DataFrame(
            sg["grid"],
            index=[fp(c) for c in sg["purchase_caps"]],
            columns=[fp(c) for c in sg["exit_caps"]],
        )
        tgt_irr_color = target_irr_disp

        def _color_irr(val):
            if pd.isna(val) or val is None:
                return ""
            return "background-color: #c3e6cb; color: #155724" if val >= tgt_irr_color else "background-color: #f5c6cb; color: #721c24"

        irr_styled = irr_grid_df.style.applymap(_color_irr).format(
            lambda v: fp(v) if v is not None and not pd.isna(v) else "—"
        )
        st.caption(f"Rows = purchase cap rates · Columns = exit cap rates · Green ≥ {fp(tgt_irr_color)} target")
        st.dataframe(irr_styled, use_container_width=True)

    # ── Sensitivity: Rate × LTV → CoC and DSCR ───────────────────────────────
    with st.expander("Sensitivity: Interest Rate × LTV → Year-1 CoC & DSCR", expanded=False):
        sg2 = sensitivity_debt(
            noi_yr1=noi,
            price=price,
            cashflows=res["cashflows"],
            exit_noi=res["exit_noi"],
            exit_cap=float(scen.get("exit_cap") or 0.08),
            closing_costs_pct=float(scen.get("closing_costs_pct") or 0.0),
            sale_costs_pct=float(scen.get("sale_costs_pct") or 0.0),
            hold_years=res["hold_years"],
            amort_years=int(scen.get("amort_years") or 25),
        )
        coc_df = pd.DataFrame(
            sg2["coc_grid"],
            index=[fp(r) for r in sg2["rates"]],
            columns=[fp(l) for l in sg2["ltvs"]],
        )
        dscr_df = pd.DataFrame(
            sg2["dscr_grid"],
            index=[fp(r) for r in sg2["rates"]],
            columns=[fp(l) for l in sg2["ltvs"]],
        )

        def _color_coc(val):
            if pd.isna(val) or val is None:
                return ""
            return "background-color: #c3e6cb; color: #155724" if val >= 0.05 else "background-color: #f5c6cb; color: #721c24"

        def _color_dscr(val):
            if pd.isna(val) or val is None:
                return ""
            return "background-color: #c3e6cb; color: #155724" if val >= 1.25 else "background-color: #f5c6cb; color: #721c24"

        st.caption("Rows = interest rate · Columns = LTV")
        coc_tab, dscr_tab = st.tabs(["Year-1 Cash-on-Cash", "DSCR"])
        with coc_tab:
            st.dataframe(
                coc_df.style.applymap(_color_coc).format(lambda v: fp(v) if v else "—"),
                use_container_width=True,
            )
        with dscr_tab:
            st.dataframe(
                dscr_df.style.applymap(_color_dscr).format(lambda v: f"{v:.2f}" if v else "—"),
                use_container_width=True,
            )

    # ── Base vs Downside ──────────────────────────────────────────────────────
    with st.expander("Base vs. Downside", expanded=True):
        bc, dc = st.columns(2)
        with bc:
            st.subheader("Base Case")
            st.metric("NOI Yr 1", fm(noi))
            st.metric("Unlevered IRR", fp(ret["unlevered_irr"]))
            st.metric("Levered IRR", fp(ret["levered_irr"]))
            st.metric("Equity Multiple", fx(ret["equity_multiple"]))
            st.metric("Total Profit", fm(ret["total_profit"]))
        with dc:
            ds = res.get("downside")
            st.subheader("Downside")
            if ds:
                vs_yr = int(scen.get("vacancy_start_year") or 0)
                st.caption(f"Tenant vacates year {vs_yr}, {scen.get('downtime_months', 12)} mo downtime")
                st.metric("Unlevered IRR", fp(ds.get("unlevered_irr")))
                st.metric("Levered IRR", fp(ds.get("levered_irr")))
                # DSCR at vacancy
                worst_dscr = min((r["dscr"] for r in ds.get("dscr_by_year", [])), default=None)
                st.metric("Worst DSCR", f"{worst_dscr:.2f}" if worst_dscr is not None else "—")
                # NOI table
                ds_rows = [
                    {
                        "Year": r["year"],
                        "NOI": fm(r["noi"]),
                        "DS": fm(-r["ds"]),
                        "DSCR": f"{r['dscr']:.2f}",
                        "Status": ds["downside_cashflows"][r["year"] - 1].get("scenario", "").replace("_", " ").title()
                        if r["year"] - 1 < len(ds["downside_cashflows"]) else "",
                    }
                    for r in ds.get("dscr_by_year", [])
                ]
                if ds_rows:
                    st.dataframe(pd.DataFrame(ds_rows), hide_index=True, use_container_width=True)
            else:
                st.info("Set 'Tenant vacates in year #' ≤ hold period in the Downside tab to see this.")

    # ── Offer helper ─────────────────────────────────────────────────────────
    with st.expander("Offer Helper — Solve for Max Price", expanded=False):
        st.caption("Enter a target and see the implied maximum price.")
        oh1, oh2 = st.columns(2)
        with oh1:
            target_cap_input = st.number_input(
                "Target cap rate (%)", min_value=0.01, max_value=0.25,
                value=float(scen.get("exit_cap") or 0.08),
                step=0.0025, format="%.4f",
                help="Maximum price = NOI ÷ target cap rate.",
                key="oh_cap",
            )
            max_price_by_cap = price_from_cap(noi, target_cap_input)
            st.metric(f"Max price at {fp(target_cap_input)}", fm(max_price_by_cap))
            st.caption(f"vs. asking: {fm(abs(max_price_by_cap - price))} {'below' if max_price_by_cap < price else 'above'} asking")

        with oh2:
            target_irr_input = st.number_input(
                "Target levered IRR (%)", min_value=0.0, max_value=0.30,
                value=target_irr,
                step=0.005, format="%.4f",
                help="Maximum price that still achieves your target IRR.",
                key="oh_irr",
            )
            max_price_by_irr = _solve_price_for_irr(
                target_irr_input, res["cashflows"], res["exit_noi"], scen, res["hold_years"]
            )
            st.metric(f"Max price at {fp(target_irr_input)} IRR", fm(max_price_by_irr))
            st.caption(f"vs. asking: {fm(abs(max_price_by_irr - price))} {'below' if max_price_by_irr < price else 'above'} asking")

    # ── Download PDF Report ───────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Download Report")
    _dl_c1, _dl_c2 = st.columns([2, 5])
    with _dl_c1:
        try:
            _pdf_bytes = build_pdf(
                deal=deal,
                scenario=scen,
                cashflows=res["cashflows"],
                debt_schedule=debt["schedule"],
                returns=ret,
                exit_noi=res["exit_noi"],
            )
            _pdf_filename = (
                f"{deal.get('name','deal').replace(' ','_')}_{scen.get('name','scenario').replace(' ','_')}.pdf"
            )
            st.download_button(
                label="⬇ Download PDF Report",
                data=_pdf_bytes,
                file_name=_pdf_filename,
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as _pdf_err:
            st.error(f"PDF generation failed: {_pdf_err}")

    # ── Compare scenarios ─────────────────────────────────────────────────────
    all_scens = get_scenarios(deal_id)
    if len(all_scens) > 1:
        with st.expander("Compare Scenarios", expanded=False):
            cmp_rows = []
            for s in all_scens:
                r = run_engine(s, deal)
                if "error" in r:
                    cmp_rows.append({"Scenario": s["name"], "Error": r["error"]})
                    continue
                cmp_rows.append(
                    {
                        "Scenario": s["name"],
                        "Price": fm(r["price"]),
                        "Cap Rate": fp(going_in_cap_rate(r["noi_yr1"], r["price"])),
                        "NOI": fm(r["noi_yr1"]),
                        "DSCR": f"{r['debt']['dscr']:.2f}",
                        "CoC Yr1": fp(r["ret"]["coc_by_year"][0]["coc"]),
                        "Lev IRR": fp(r["ret"]["levered_irr"]),
                        "Eq. Mult.": fx(r["ret"]["equity_multiple"]),
                        "Exit $": fm(r["ret"]["net_exit"]),
                    }
                )
            st.dataframe(pd.DataFrame(cmp_rows), hide_index=True, use_container_width=True)


# ── Page: Due Diligence ───────────────────────────────────────────────────────

def page_due_diligence():
    deal_id = st.session_state.get("deal_id")
    if not deal_id:
        st.info("No deal open. Go to **Pipeline** and open a deal.")
        return
    deal = get_deal(deal_id)
    st.header(f"Due Diligence — {deal['name']}")
    ensure_dd_items(deal_id)
    items = get_dd_items(deal_id)

    status_order = {"open": 0, "done": 1, "n/a": 2}
    items_sorted = sorted(items, key=lambda x: (status_order.get(x["status"], 99), x["sort_order"]))

    open_ct = sum(1 for i in items_sorted if i["status"] == "open")
    done_ct = sum(1 for i in items_sorted if i["status"] == "done")
    na_ct = sum(1 for i in items_sorted if i["status"] == "n/a")
    st.progress(done_ct / len(items_sorted) if items_sorted else 0,
                text=f"{done_ct} done · {open_ct} open · {na_ct} n/a")

    STATUS_OPTS = ["open", "done", "n/a"]
    STATUS_ICON = {"open": "🔲", "done": "✅", "n/a": "⬜"}

    for item in items_sorted:
        with st.expander(f"{STATUS_ICON.get(item['status'], '')} {item['item_name']}", expanded=(item["status"] == "open")):
            dc1, dc2, dc3 = st.columns([2, 2, 1])
            new_status = dc1.selectbox(
                "Status", STATUS_OPTS,
                index=STATUS_OPTS.index(item["status"]) if item["status"] in STATUS_OPTS else 0,
                key=f"dd_status_{item['id']}",
            )
            new_date = dc2.date_input(
                "Completed date",
                value=parse_date(item.get("completed_date")),
                key=f"dd_date_{item['id']}",
            )
            new_notes = st.text_area(
                "Notes", value=item.get("notes", ""),
                key=f"dd_notes_{item['id']}", height=60,
            )
            if dc3.button("Save", key=f"dd_save_{item['id']}"):
                update_dd_item(item["id"], new_status, new_notes,
                               str(new_date) if new_date else None)
                st.success("Saved")
                st.rerun()

    st.markdown("---")
    st.subheader("Add custom item")
    new_item_name = st.text_input("Item name", key="new_dd_item")
    if st.button("Add item") and new_item_name.strip():
        add_dd_item(deal_id, new_item_name.strip())
        st.rerun()


# ── Page: Notes ───────────────────────────────────────────────────────────────

def page_notes():
    deal_id = st.session_state.get("deal_id")
    if not deal_id:
        st.info("No deal open. Go to **Pipeline** and open a deal.")
        return
    deal = get_deal(deal_id)
    st.header(f"Notes — {deal['name']}")

    with st.form("add_note_form", clear_on_submit=True):
        note_text = st.text_area("New note", height=100, placeholder="Type your note here…")
        if st.form_submit_button("Add note") and note_text.strip():
            add_note(deal_id, note_text.strip())
            st.rerun()

    notes = get_notes(deal_id)
    if not notes:
        st.info("No notes yet.")
        return

    for note in notes:
        with st.container():
            nc1, nc2 = st.columns([5, 1])
            nc1.markdown(f"**{(note.get('created_at') or '')[:16]}**")
            nc1.write(note.get("content", ""))
            if nc2.button("Delete", key=f"del_note_{note['id']}"):
                delete_note(note["id"])
                st.rerun()
            st.divider()


def page_education():
    st.header("📚 CRE Education — Terms & Benchmarks")
    st.caption("A reference guide for commercial real estate analysis. Click any section to expand.")

    tab_glossary, tab_benchmarks = st.tabs(["📖 Glossary", "📊 Investor Benchmarks"])

    # ── GLOSSARY TAB ──────────────────────────────────────────────────────────
    with tab_glossary:

        # ---------- Cash Flow & NOI ----------
        with st.expander("💵 Cash Flow & NOI Terms", expanded=True):
            st.markdown("""
| Term | Definition |
|---|---|
| **Gross Scheduled Rent (GSR)** | The total rent the tenant is contractually obligated to pay if 100% occupied — before any deductions. |
| **Vacancy & Credit Loss** | A deduction (usually 5–10%) representing the risk that space sits empty or tenants don't pay. Always underwritten even with a tenant in place. |
| **Effective Gross Income (EGI)** | `GSR − Vacancy`. The income you actually expect to collect. |
| **Operating Expenses (OpEx)** | The landlord's out-of-pocket costs: property management, non-reimbursable repairs, insurance (if landlord-paid), etc. Does NOT include mortgage payments. |
| **NOI (Net Operating Income)** | `EGI − OpEx`. The single most important number in CRE — the property's earnings before debt and taxes. Cap rates, valuations, and DSCR are all based on NOI. |
| **Capital Reserve** | Money set aside annually for large future capital expenses (roof replacement, HVAC, parking). Not spent today, but held back from "free" cash. Typical: $0.10–$0.50/SF/yr. |
| **Net Cash Flow (Before Debt)** | `NOI − Capital Reserve`. What the property produces before the bank takes its cut. |
| **Debt Service (DS)** | Your total annual mortgage payment (principal + interest). Fixed on a standard amortizing loan. |
| **After Debt Service (ADS)** | `Net CF − Debt Service`. The cash left in your pocket as the equity owner each year. Can be negative on a value-add or overleveraged deal. |
| **Cash-on-Cash Return (CoC)** | `ADS ÷ Equity Invested`. Your annual cash yield on the cash you put in. Ignores appreciation — pure income return. A 7% CoC means you earn $7 for every $100 invested each year. |
| **CAM (Common Area Maintenance)** | Charges passed to tenants for shared building expenses: hallways, parking lots, landscaping, roof. In a NNN lease, tenants pay CAM directly. |
""")

        # ---------- Valuation ----------
        with st.expander("🏢 Valuation & Pricing Terms"):
            st.markdown("""
| Term | Definition |
|---|---|
| **Cap Rate (Capitalization Rate)** | `NOI ÷ Price`. Expresses the property's yield as a percentage, ignoring financing. A 7% cap means you buy $1 of NOI for every $14.28 of price. Lower cap = higher price relative to income (better neighborhood / stronger tenant). |
| **Going-in Cap Rate** | The cap rate at your purchase price, using Year-1 NOI. This is what you're actually paying for the income stream on Day 1. |
| **Exit Cap Rate** | The cap rate you assume at sale — typically 25–75 bps higher than going-in (cap rate expansion = lower exit price). Conservative underwriting uses a wider spread. |
| **Implied Price / Price Ladder** | Given a NOI and a cap rate, the implied value: `NOI ÷ Cap Rate`. The Price Ladder shows this across a range of cap rates to bracket fair value. |
| **Price per SF** | `Purchase Price ÷ Building SF`. A quick cross-check against comparable sales. Retail in Carytown Richmond: ~$250–$400/SF is market; $459/SF is a premium. |
| **GRM (Gross Rent Multiplier)** | `Price ÷ Annual Gross Rent`. Simpler than cap rate — ignores expenses. Lower = cheaper relative to rent. Useful for quick screening; less reliable than NOI-based metrics. |
| **Stabilized Value** | What the property is worth once fully leased at market rent. Used to underwrite value-add deals: you buy at a discount, lease it up, then sell (or refinance) at stabilized value. |
| **Value-Add** | A strategy where you buy a property below stabilized value (vacant, below-market rent, deferred maintenance), improve it, and capture the upside in value. Higher risk, higher return. |
| **Core / Core-Plus** | Lower-risk strategies: strong tenants, long leases, minimal capex needed. Lower returns (5–9% IRR) but very predictable. |
| **Reversion / Terminal Value** | The projected sale price at the end of your hold period, calculated as `Exit-Year NOI ÷ Exit Cap Rate`. Also called the "exit value." |
""")

        # ---------- Debt ----------
        with st.expander("🏦 Debt & Financing Terms"):
            st.markdown("""
| Term | Definition |
|---|---|
| **LTV (Loan-to-Value)** | `Loan Amount ÷ Purchase Price`. A 65% LTV means you borrow $65 for every $100 of price and put in $35 equity. Higher LTV = more leverage = more risk and return. |
| **DSCR (Debt Service Coverage Ratio)** | `NOI ÷ Annual Debt Service`. Lenders require this above 1.20–1.30x. Below 1.0x means the property can't pay its own mortgage from income — you're feeding it cash. |
| **Debt Yield** | `NOI ÷ Loan Amount`. A lender metric that doesn't depend on cap rate or LTV. Lenders typically require 8–10%+. It answers: "If I foreclose, what yield do I get?" |
| **Loan Constant** | `Annual Debt Service ÷ Loan Amount`. The percentage of the loan you pay each year (principal + interest). At 7.25% / 25-yr amort, the constant is ~8.67%. If your cap rate is below the loan constant, you have **negative leverage**. |
| **Positive vs. Negative Leverage** | **Positive**: Cap rate > Loan constant → debt boosts your equity return. **Negative**: Cap rate < Loan constant → debt *hurts* your equity return (the Nansemond deal: 2.5% cap vs. 8.67% constant). |
| **Amortization** | How long the loan is paid down over. A 25-yr amort means the balance reaches zero in 25 years. Longer amort = lower payments = better cash flow, but slower equity build. |
| **Interest Only (IO)** | A period where you pay only interest, not principal. Lowers early payments, improves early CoC, but the full balance stays outstanding longer. Common on bridge loans. |
| **Loan Fees / Points** | Upfront origination fee charged by the lender: 1 point = 1% of loan. Paid at closing; increases your effective all-in cost of capital. |
| **Bridge Loan** | Short-term (1–3 yr) financing for value-add or transitional assets. Higher rate, interest-only, used while you stabilize — then you refinance into permanent debt. |
| **Recourse vs. Non-Recourse** | **Recourse**: lender can come after your personal assets if you default. **Non-recourse**: limited to the property (with carve-outs for fraud, waste, etc.). Non-recourse is standard on large CMBS and agency loans. |
""")

        # ---------- Returns ----------
        with st.expander("📈 Return Metrics"):
            st.markdown("""
| Term | Definition |
|---|---|
| **IRR (Internal Rate of Return)** | The single annualized return that makes the NPV of all cash flows (including the sale) equal to zero. Accounts for the timing of every dollar in and out. It's the "apples-to-apples" return you can compare to a stock, bond, or other investment. |
| **Levered IRR** | IRR calculated on equity cash flows (after debt service, after paying off the loan at sale). This is your actual return as the equity investor. |
| **Unlevered IRR** | IRR calculated at the property level, as if you paid all cash. Strips out financing to show the pure real estate return. Compare to your cost of capital to assess whether debt helps or hurts. |
| **Equity Multiple** | `Total Equity Received ÷ Total Equity Invested`. 2.0x means you doubled your money over the hold. Easy to understand but ignores time — 2.0x in 3 years is great; 2.0x in 15 years is poor. |
| **NPV (Net Present Value)** | The present value of all future cash flows discounted at your target rate, minus your initial investment. Positive NPV = deal creates value above your hurdle rate. |
| **Hurdle Rate / Target IRR** | The minimum return you'll accept to do the deal, accounting for risk. Common targets: 8–10% (core), 12–15% (value-add), 18%+ (opportunistic). |
| **CoC Return (Cash-on-Cash)** | Your annual income return on invested equity. Does not include appreciation. Preferred by income-focused investors. |
| **Total Return** | CoC income + appreciation. The full picture over the hold period. |
| **Promote / Carried Interest** | In a fund or partnership, the GP (general partner / sponsor) earns a share of profits above the hurdle rate as compensation for finding and managing the deal. Typically 20% of profits above 8% preferred return. |
| **Preferred Return (Pref)** | The LP investors receive this return (usually 6–8%) before the GP takes any profit share. Protects passive investors. |
""")

        # ---------- Lease ----------
        with st.expander("📄 Lease Terms"):
            st.markdown("""
| Term | Definition |
|---|---|
| **Absolute NNN (Absolute Triple-Net)** | Tenant pays ALL expenses: taxes, insurance, maintenance, roof, structure. Landlord receives a truly passive check. Highest-credit tenants (Walgreens, McDonald's). |
| **NNN (Triple-Net)** | Tenant pays taxes, insurance, and CAM. Landlord responsible for roof and structure. Most common retail/industrial lease type. |
| **NN (Double-Net)** | Tenant pays taxes and insurance. Landlord pays maintenance, roof, structure. Less landlord-friendly than NNN. |
| **Gross Lease** | Landlord pays all expenses; tenant pays a flat rent. Common in office. Landlord bears all cost risk (if taxes spike, it comes out of NOI). |
| **Modified Gross** | Hybrid: tenant pays base expenses up to a "base year" amount; landlord and tenant share increases above that. |
| **Base Rent** | The contractual rent before any additions. |
| **Escalation** | Rent increases built into the lease. Three types: (1) **Percent**: fixed % increase every N years. (2) **CPI**: tied to inflation index. (3) **Fixed steps**: specific dollar amounts on specific dates. |
| **TI (Tenant Improvements)** | Cash or construction provided by the landlord to customize the space for the tenant. Negotiated per deal. Typical ranges: $20–$80/SF for office; $10–$40/SF for retail. |
| **LC (Leasing Commissions)** | Fees paid to the tenant's broker (and sometimes your own broker) when a new lease is signed. Typically 4–6% of total lease value. |
| **WALT (Weighted Average Lease Term)** | The average remaining lease duration weighted by rent. A WALT of 7 means tenants have 7 years left on average. Higher WALT = more income security. |
| **ROFR (Right of First Refusal)** | Tenant has the right to match any outside offer before the landlord can accept it. Complicates a sale — buyers don't love competing with a ROFR. |
| **ROFO (Right of First Offer)** | Landlord must offer the tenant the space (or property) first before going to market. Less burdensome than ROFR. |
| **Go-Dark Clause** | A lease provision allowing the tenant to stop operating (close the store) while still paying rent. Dangerous for co-tenancy clauses and nearby tenants. |
| **Co-Tenancy Clause** | Allows a tenant to reduce rent or terminate if an anchor tenant leaves. Common in shopping centers — if Walmart leaves, inline tenants may trigger co-tenancy. |
| **Holdover** | When a lease expires and the tenant stays without signing a renewal. Usually reverts to month-to-month at a higher rate (110–150% of last rent). Creates uncertainty. |
| **Renewal Options** | Tenant's contractual right to extend the lease for a set period at a pre-agreed rent or market rent. Gives the tenant certainty; reduces the landlord's ability to re-lease at higher market rates. |
""")

        # ---------- Property / Market ----------
        with st.expander("🗺️ Property & Market Terms"):
            st.markdown("""
| Term | Definition |
|---|---|
| **Building SF / GLA** | Gross Leasable Area — the total rentable square footage. |
| **FAR (Floor Area Ratio)** | `Building SF ÷ Land SF`. Measures density. A 0.5 FAR on an acre = 21,780 SF of building. Zoning sets the maximum. |
| **Absorption** | The rate at which available space is leased in a market. Positive net absorption = more space is being leased than vacated = tightening market. |
| **Market Vacancy Rate** | The percentage of all space in a market that is available to rent. Low vacancy (< 5%) = landlord market; high vacancy (> 10–12%) = tenant market with concessions. |
| **Rent/SF** | Annualized rent per square foot. The standard unit for comparing lease comps. Always confirm NNN vs. gross — an apples-to-apples comparison requires the same lease structure. |
| **Comp (Comparable)** | A recent transaction (sale or lease) used to support pricing. The closer in size, location, lease type, and building age, the better the comp. |
| **Cap Rate Compression** | When cap rates fall over time (prices rise faster than NOI). Creates appreciation — you buy at 6%, market moves to 5%, your property value increases ~20%. |
| **NOI Growth** | Rent escalations + occupancy gains over time. The compounding engine of real estate returns over long holds. |
| **Phase I Environmental** | A desk review of environmental records and a site inspection. Required by most lenders. Identifies whether a Phase II (actual soil/water testing) is needed. |
| **Survey** | An ALTA survey confirms boundaries, easements, encroachments, and legal description. Required at closing by most title insurers. |
| **Title Insurance** | Protects the buyer (and lender) against claims arising from defects in the chain of title. A standard closing cost. |
""")

    # ── BENCHMARKS TAB ──────────────────────────────────────────────────────
    with tab_benchmarks:
        st.subheader("Standard Investor Benchmarks")
        st.caption("These are the ranges widely used by institutional and private equity CRE investors. Your specific deal and market may differ.")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### 🎯 Return Targets by Strategy")
            st.markdown("""
| Strategy | Levered IRR | Equity Multiple | CoC (Stabilized) |
|---|---|---|---|
| **Core** | 6–9% | 1.4–1.7x | 4–6% |
| **Core-Plus** | 9–13% | 1.6–2.0x | 5–8% |
| **Value-Add** | 13–18% | 1.8–2.5x | 6–10% |
| **Opportunistic** | 18–25%+ | 2.0–3.0x+ | Often negative early |
""")
            st.info("Rule of thumb: the harder the deal (vacant, distressed, development), the higher the return you should demand to compensate for risk.")

            st.markdown("#### 🏦 Lender Requirements (Typical)")
            st.markdown("""
| Metric | Typical Lender Minimum |
|---|---|
| **DSCR** | 1.20–1.30x (bank); 1.20x (CMBS) |
| **LTV** | 65–75% (stabilized); 55–65% (value-add) |
| **Debt Yield** | 8–10%+ |
| **Occupancy at underwriting** | 85–90%+ (for standard loans) |
""")
            st.warning("If your going-in DSCR is below 1.0x, most conventional lenders will pass. You'll need equity, a bridge loan, or seller financing.")

            st.markdown("#### 💰 Cap Rates by Asset Class (US, 2024–2025)")
            st.markdown("""
| Asset Class | Typical Cap Rate Range |
|---|---|
| **Industrial / Warehouse** | 4.5–6.5% |
| **Multifamily (apartments)** | 4.5–6.5% |
| **Grocery-anchored retail** | 5.5–7.0% |
| **Single-tenant NNN (investment grade)** | 4.5–6.0% |
| **Single-tenant NNN (non-rated)** | 6.0–8.5% |
| **Strip / neighborhood retail** | 6.0–8.5% |
| **Small-bay retail / medical office** | 6.5–9.0% |
| **CBD office** | 6.0–9.0% (wide range post-COVID) |
| **Suburban office** | 7.5–11%+ |
""")
            st.info("Lower cap rate = lower yield but more stable / institutional asset. Higher cap rate = higher yield but more risk or lower quality.")

        with col2:
            st.markdown("#### 📐 Underwriting Assumptions (Market Standard)")
            st.markdown("""
| Assumption | Typical Range | Notes |
|---|---|---|
| **Vacancy & Credit Loss** | 5–10% | Even on occupied NNN deals; 3–5% minimum |
| **Management Fee** | 3–6% of EGI | Lower for NNN; higher for multifamily |
| **Capital Reserve** | $0.10–$0.50/SF/yr | Higher for older buildings |
| **Roof Reserve** | $0.05–$0.15/SF/yr | Separate from cap reserve |
| **TI (new lease)** | $15–$80/SF | Retail lower; office higher |
| **Leasing Commissions** | 4–6% of lease value | Varies by market |
| **Exit Cap Spread** | +25–75 bps vs. going-in | Conservative = wider spread |
| **Closing Costs (buy)** | 1–3% of price | Transfer taxes, title, legal |
| **Sale Costs (sell)** | 3–5% of price | Broker commission + closing |
| **Hold Period** | 5–10 years | Shorter for opportunistic; longer for core |
""")

            st.markdown("#### 📊 Key Ratios — Quick Checks")
            st.markdown("""
| Check | What It Tells You |
|---|---|
| **Cap Rate vs. Loan Constant** | If cap rate < loan constant → negative leverage → debt hurts returns. |
| **Going-in vs. Exit Cap** | Buying wide, selling tight = appreciation play. Buying tight, selling wider = value-add required. |
| **NOI / Loan Amount (Debt Yield)** | If debt yield < 8%, lender is taking a lot of risk — deal may not qualify for conventional financing. |
| **DSCR Breakeven Occupancy** | At what occupancy does NOI = Debt Service? You want a big cushion here. |
| **Price/SF vs. Replacement Cost** | Buying below replacement cost provides downside protection. |
""")

            st.markdown("#### 🔑 The Big Four Numbers")
            st.markdown("""
Every CRE investor tracks these four on every deal:

| # | Metric | Why It Matters |
|---|---|---|
| **1** | Cap Rate | What am I paying for income? |
| **2** | DSCR | Can the property pay its own mortgage? |
| **3** | Levered IRR | What is my total annualized return? |
| **4** | Equity Multiple | How many times do I get my money back? |
""")
            st.success("A deal that clears 6%+ cap rate, 1.25x+ DSCR, 12%+ levered IRR, and 1.8x+ equity multiple across scenarios is generally considered well-underwritten for value-add.")

        st.divider()
        st.markdown("#### ⚡ Common Rules of Thumb")
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            st.markdown("""
**Leverage**
- Every 100 bps of positive leverage adds ~150–200 bps to levered IRR
- Going from 65% to 75% LTV typically adds 200–400 bps levered IRR (if cap > constant)
- Never lever a deal where cap rate < loan constant
""")
        with rc2:
            st.markdown("""
**Exit Cap Estimation**
- Add 25 bps for each 2–3 years of hold
- Add 50 bps if tenant credit is weaker
- Add 50–100 bps if market is uncertain
- Subtract 25 bps if market has historically compressed
""")
        with rc3:
            st.markdown("""
**NOI Growth**
- 2% escalation/yr ≈ doubles NOI in ~35 years
- 3% escalation/yr ≈ doubles NOI in ~24 years
- Every $1K increase in annual NOI = $12,500–$20,000 more value at a 5–8% cap rate
""")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="CRE Deal Analyzer",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_db()

    # Session state initialization
    for key, default in [
        ("deal_id", None),
        ("scenario_id", None),
        ("nav_radio", "Pipeline"),
        ("nav_pending", None),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # Apply any pending programmatic navigation BEFORE the radio widget renders
    if st.session_state.nav_pending:
        st.session_state.nav_radio = st.session_state.nav_pending
        st.session_state.nav_pending = None

    with st.sidebar:
        st.title("🏢 CRE Analyzer")
        page = st.radio("", PAGES, key="nav_radio")
        st.markdown("---")
        st.link_button("📚 CRE Reference Guide →", url="https://claude.ai/artifact/YKazA9WPH3s368wBVZ19k1", use_container_width=True)

        # Open deal context
        if st.session_state.deal_id:
            deal = get_deal(st.session_state.deal_id)
            if deal:
                st.markdown("---")
                st.caption("Open deal")
                st.write(f"**{deal['name']}**")
                st.caption(deal.get("tenant", ""))

                scens = get_scenarios(st.session_state.deal_id)
                if scens:
                    scen_labels = [s["name"] for s in scens]
                    scen_ids = [s["id"] for s in scens]
                    cur_idx = 0
                    if st.session_state.scenario_id in scen_ids:
                        cur_idx = scen_ids.index(st.session_state.scenario_id)
                    sel = st.selectbox(
                        "Scenario", range(len(scen_labels)),
                        format_func=lambda i: scen_labels[i],
                        index=cur_idx,
                        key="sidebar_scen",
                    )
                    st.session_state.scenario_id = scen_ids[sel]

                    sb_c1, sb_c2 = st.columns(2)
                    if sb_c1.button("＋ New", help="Clone current scenario", use_container_width=True):
                        new_id = clone_scenario(scen_ids[sel], scens[sel]["name"] + " (copy)")
                        st.session_state.scenario_id = new_id
                        st.rerun()
                    if sb_c2.button("🗑 Delete", help="Delete current scenario", use_container_width=True):
                        if len(scens) > 1:
                            delete_scenario(scen_ids[sel])
                            remaining = get_scenarios(st.session_state.deal_id)
                            st.session_state.scenario_id = remaining[0]["id"] if remaining else None
                            st.rerun()
                        else:
                            st.warning("Can't delete the only scenario.")

                if st.button("Close deal", use_container_width=True):
                    st.session_state.deal_id = None
                    st.session_state.scenario_id = None
                    st.session_state.nav_pending = "Pipeline"
                    st.rerun()

    if page == "Pipeline":
        page_pipeline()
    elif page == "New / Edit Deal":
        page_deal_form()
    elif page == "Analysis":
        page_analysis()
    elif page == "Due Diligence":
        page_due_diligence()
    elif page == "Notes":
        page_notes()


if __name__ == "__main__":
    main()
