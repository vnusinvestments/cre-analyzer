"""
PDF report generator for CRE deal analysis.
Uses fpdf2 to produce a professional single-page deal summary.
"""
from __future__ import annotations
from datetime import date
from typing import Dict, List, Optional
from fpdf import FPDF


# ── Palette ───────────────────────────────────────────────────────────────────
DARK_BG   = (30, 35, 48)
ACCENT    = (99, 149, 255)
WHITE     = (255, 255, 255)
LIGHT_ROW = (245, 246, 250)
MID_ROW   = (235, 237, 244)
TEXT_DARK = (30, 35, 48)
TEXT_MID  = (90, 95, 115)
GREEN     = (34, 170, 100)
RED       = (220, 60, 60)
BORDER    = (200, 205, 220)


def _fm(v: float) -> str:
    """Format as $1,234,567"""
    return f"${v:,.0f}"


def _fp(v: Optional[float]) -> str:
    """Format as 9.33%"""
    if v is None:
        return "-"
    return f"{v:.2f}%"


def _fmx(v: Optional[float]) -> str:
    """Format as 5.16x"""
    if v is None:
        return "-"
    return f"{v:.2f}x"


class DealReport(FPDF):
    def __init__(self):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.set_auto_page_break(auto=False)
        self.set_margins(0, 0, 0)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _rgb(self, color):
        self.set_fill_color(*color)

    def _text_color(self, color):
        self.set_text_color(*color)

    def _draw_rect(self, x, y, w, h, color, style="F"):
        self._rgb(color)
        self.rect(x, y, w, h, style)

    def _cell(self, x, y, w, h, txt, font_size=9, bold=False,
              color=TEXT_DARK, align="L", bg=None):
        if bg:
            self._draw_rect(x, y, w, h, bg)
        self.set_xy(x, y)
        self.set_font("Helvetica", "B" if bold else "", font_size)
        self._text_color(color)
        self.cell(w, h, str(txt), align=align)

    # ── section label ─────────────────────────────────────────────────────────

    def _section(self, x, y, w, label):
        self._draw_rect(x, y, w, 6, ACCENT)
        self.set_xy(x + 2, y)
        self.set_font("Helvetica", "B", 8)
        self._text_color(WHITE)
        self.cell(w - 2, 6, label.upper(), align="L")

    # ── key metric tile ───────────────────────────────────────────────────────

    def _tile(self, x, y, w, label, value, sub=None, value_color=TEXT_DARK):
        self._draw_rect(x, y, w, 20, LIGHT_ROW)
        self.set_draw_color(*BORDER)
        self.rect(x, y, w, 20)
        # label
        self.set_xy(x + 2, y + 2)
        self.set_font("Helvetica", "", 7)
        self._text_color(TEXT_MID)
        self.cell(w - 4, 4, label, align="C")
        # value
        self.set_xy(x + 2, y + 6)
        self.set_font("Helvetica", "B", 13)
        self._text_color(value_color)
        self.cell(w - 4, 8, value, align="C")
        # sub
        if sub:
            self.set_xy(x + 2, y + 14)
            self.set_font("Helvetica", "", 7)
            self._text_color(TEXT_MID)
            self.cell(w - 4, 4, sub, align="C")


def build_pdf(
    deal: Dict,
    scenario: Dict,
    cashflows: List[Dict],
    debt_schedule: List[Dict],
    returns: Dict,
    exit_noi: float,
) -> bytes:
    """
    Generate a landscape A4 PDF and return the raw bytes.

    Parameters match what app.py already computes on the Analysis page.
    """
    pdf = DealReport()
    pdf.add_page()

    PW, PH = 297, 210   # A4 landscape mm
    PAD = 6

    # ── HEADER BAR ────────────────────────────────────────────────────────────
    pdf._draw_rect(0, 0, PW, 18, DARK_BG)
    pdf.set_xy(PAD, 3)
    pdf.set_font("Helvetica", "B", 14)
    pdf._text_color(WHITE)
    pdf.cell(180, 8, deal.get("name", "Deal Analysis"), align="L")

    address_parts = [deal.get("address", ""), deal.get("city", ""), deal.get("state", "")]
    address_str = ", ".join(p for p in address_parts if p)
    pdf.set_xy(PAD, 11)
    pdf.set_font("Helvetica", "", 8)
    pdf._text_color(ACCENT)
    pdf.cell(180, 5, address_str, align="L")

    # scenario name + date top-right
    pdf.set_xy(PW - 95, 3)
    pdf.set_font("Helvetica", "B", 8)
    pdf._text_color(WHITE)
    pdf.cell(90, 5, f"Scenario: {scenario.get('name', '')}", align="R")
    pdf.set_xy(PW - 95, 9)
    pdf.set_font("Helvetica", "", 7)
    pdf._text_color(ACCENT)
    pdf.cell(90, 5, f"Generated {date.today().strftime('%B %d, %Y')}", align="R")

    # ── METRICS ROW ───────────────────────────────────────────────────────────
    bsf = float(deal.get("building_sf") or 0)
    price = float(scenario.get("price") or 0)
    equity = float(returns.get("equity") or 0)
    base_rent = float(scenario.get("base_annual_rent") or 0)
    cap_rate = base_rent / price if price else 0
    rent_sf = base_rent / bsf if bsf else 0
    levered_irr = returns.get("levered_irr")
    eq_mult = returns.get("equity_multiple")
    total_profit = float(returns.get("total_profit") or 0)

    yr1_cf = cashflows[0] if cashflows else {}
    yr1_noi = float(yr1_cf.get("noi") or 0)
    yr1_ds = float(debt_schedule[0].get("annual_ds") or 0) if debt_schedule else 0
    yr1_dscr = yr1_noi / yr1_ds if yr1_ds else 0

    tile_y = 21
    tile_h = 20
    tw = (PW - 2 * PAD) / 8

    irr_color = GREEN if (levered_irr or 0) >= 0.12 else (RED if (levered_irr or 0) < 0.08 else TEXT_DARK)

    tiles = [
        ("Price",           _fm(price),         f"${price/bsf:.0f}/SF" if bsf else ""),
        ("Cap Rate",        _fp(cap_rate * 100), "Stabilized"),
        ("Rent / SF",       f"${rent_sf:.2f}",   f"{_fm(base_rent)}/yr"),
        ("Total Equity",    _fm(equity),         "All-in cash"),
        ("Levered IRR",     _fp((levered_irr or 0) * 100), "10-yr hold"),
        ("Equity Multiple", _fmx(eq_mult),       "Total return"),
        ("Yr 1 DSCR",       f"{yr1_dscr:.2f}x", "incl. pre-lease"),
        ("Total Profit",    _fm(total_profit),   "Net over 10 yrs"),
    ]

    for i, (lbl, val, sub) in enumerate(tiles):
        vc = irr_color if lbl == "Levered IRR" else (GREEN if lbl == "Total Profit" else TEXT_DARK)
        pdf._tile(PAD + i * tw, tile_y, tw - 1, lbl, val, sub, value_color=vc)

    # ── LEFT COLUMN: Purchase + Debt + Lease ──────────────────────────────────
    col1_x = PAD
    col1_w = 80
    col2_x = col1_x + col1_w + 3
    col2_w = 80
    col3_x = col2_x + col2_w + 3
    col3_w = PW - col3_x - PAD

    row_y = tile_y + tile_h + 4
    row_h = 5.2

    def kv_rows(x, y, w, rows, header=None):
        """Draw alternating key-value rows, return new y."""
        if header:
            pdf._section(x, y, w, header)
            y += 7
        for i, (k, v) in enumerate(rows):
            bg = LIGHT_ROW if i % 2 == 0 else WHITE
            pdf._draw_rect(x, y, w, row_h, bg)
            pdf._cell(x + 2, y + 0.8, w * 0.55, row_h - 0.8, k, font_size=8, color=TEXT_MID)
            pdf._cell(x + w * 0.55, y + 0.8, w * 0.42, row_h - 0.8, v, font_size=8, bold=True,
                      color=TEXT_DARK, align="R")
            y += row_h
        return y

    loan = float(scenario.get("ltv", 0)) * price
    loan_fee = float(scenario.get("loan_fee_pct", 0)) * loan
    closing_costs = float(scenario.get("closing_costs_pct", 0)) * price
    prelease = float(scenario.get("prelease_cost") or 0)
    monthly_ds = yr1_ds / 12

    purchase_rows = [
        ("Purchase Price",      _fm(price)),
        ("Down Payment",        f"{(1-scenario.get('ltv',0))*100:.0f}% - {_fm(price*(1-scenario.get('ltv',0)))}"),
        ("Loan Amount",         _fm(loan)),
        ("Closing Costs",       _fm(closing_costs)),
        ("Loan / Broker Fee",   _fm(loan_fee)),
    ]
    if prelease > 0:
        purchase_rows.append(("Pre-lease Cost", _fm(prelease)))
    purchase_rows.append(("Total Equity",    _fm(equity)))

    y1 = kv_rows(col1_x, row_y, col1_w, purchase_rows, "Purchase")

    debt_rows = [
        ("Interest Rate",   f"{float(scenario.get('rate',0))*100:.2f}%"),
        ("Amortization",    f"{scenario.get('amort_years',30)} years"),
        ("LTV",             f"{float(scenario.get('ltv',0))*100:.0f}%"),
        ("Monthly P&I",     _fm(monthly_ds)),
        ("Annual Debt Svc", _fm(yr1_ds)),
        ("Loan Constant",   f"{yr1_ds/loan*100:.2f}%" if loan else "—"),
        ("Exit Loan Bal.",  _fm(float(returns.get("final_loan_balance") or 0))),
    ]
    y1 = kv_rows(col1_x, y1 + 3, col1_w, debt_rows, "Debt")

    # ── MIDDLE COLUMN: Lease ─────────────────────────────────────────────────
    ls = scenario.get("lease_start", "")
    le = scenario.get("lease_expiration", "")
    acq = scenario.get("analysis_start", "")
    esc_pct = float(scenario.get("escalation_pct", 0)) * 100
    renewal_count = int(scenario.get("renewal_count") or 0)
    renewal_years = int(scenario.get("renewal_years") or 5)
    lease_type_map = {
        "absolute_nnn": "Absolute NNN",
        "nnn": "NNN",
        "nn": "NN",
        "gross": "Gross",
    }
    lease_type = lease_type_map.get(scenario.get("lease_type", ""), scenario.get("lease_type", ""))

    lease_rows = [
        ("Lease Type",       lease_type),
        ("Base Rent / SF",   f"${rent_sf:.2f}"),
        ("Annual Base Rent", _fm(base_rent)),
        ("Acquisition Date", str(acq)),
        ("Lease Start",      str(ls)),
        ("Lease Expiration", str(le)),
        ("Escalation",       f"{esc_pct:.1f}%/yr"),
        ("Renewal Options",  f"{renewal_count} x {renewal_years} yr" if renewal_count else "None"),
        ("Building SF",      f"{bsf:,.0f} SF"),
        ("Hold Period",      f"{scenario.get('hold_years', 10)} years"),
    ]
    y2 = kv_rows(col2_x, row_y, col2_w, lease_rows, "Lease")

    # ── EXIT & RETURNS ─────────────────────────────────────────────────────────
    gross_exit = float(returns.get("gross_exit") or 0)
    net_exit = float(returns.get("net_exit") or 0)
    final_lb = float(returns.get("final_loan_balance") or 0)
    exit_cap = float(scenario.get("exit_cap", 0.08)) * 100
    sale_costs_pct = float(scenario.get("sale_costs_pct", 0.05)) * 100
    unlev_irr = returns.get("unlevered_irr")
    avg_coc = float(returns.get("avg_coc") or 0)

    exit_rows = [
        ("Exit NOI (Yr 11)",   _fm(exit_noi)),
        ("Exit Cap Rate",      f"{exit_cap:.1f}%"),
        ("Gross Exit Value",   _fm(gross_exit)),
        ("Sale Costs",         f"{sale_costs_pct:.1f}% - {_fm(gross_exit*sale_costs_pct/100)}"),
        ("Loan Payoff",        _fm(final_lb)),
        ("Net Exit Proceeds",  _fm(net_exit - final_lb)),
    ]
    y3 = kv_rows(col3_x, row_y, col3_w, exit_rows, "Exit")

    return_rows = [
        ("Total Equity In",    _fm(equity)),
        ("Total Equity Out",   _fm(equity + total_profit)),
        ("Total Profit",       _fm(total_profit)),
        ("Equity Multiple",    _fmx(eq_mult)),
        ("Levered IRR",        _fp((levered_irr or 0) * 100)),
        ("Unlevered IRR",      _fp((unlev_irr or 0) * 100)),
        ("Avg Cash-on-Cash",   f"{avg_coc*100:.2f}%"),
    ]
    y3 = kv_rows(col3_x, y3 + 3, col3_w, return_rows, "Returns")

    # ── CASH FLOW TABLE ────────────────────────────────────────────────────────
    cf_y = max(y1, y2, y3) + 4
    cf_x = PAD
    cf_w = PW - 2 * PAD

    # Check if we have space; if not, just skip the table gracefully
    available_h = PH - cf_y - 4
    if available_h >= 30:
        pdf._section(cf_x, cf_y, cf_w, "Annual Cash Flow")
        cf_y += 7

        # header
        cols = [("Yr", 8), ("Period", 38), ("NOI", 24), ("Debt Svc", 24),
                ("After DS", 24), ("DSCR", 18), ("CoC", 18), ("Loan Bal.", 26)]
        hx = cf_x
        pdf._draw_rect(cf_x, cf_y, cf_w, 5.5, DARK_BG)
        for label, cw in cols:
            pdf.set_xy(hx + 1, cf_y + 0.8)
            pdf.set_font("Helvetica", "B", 7)
            pdf._text_color(WHITE)
            pdf.cell(cw - 1, 4.5, label, align="L" if label in ("Yr", "Period") else "R")
            hx += cw
        cf_y += 5.5

        hold = int(scenario.get("hold_years", 10))
        row_height = min(5.0, (PH - cf_y - 4) / max(hold, 1))
        row_height = max(row_height, 3.5)

        for i, cf in enumerate(cashflows[:hold]):
            ds = float(debt_schedule[i]["annual_ds"]) if i < len(debt_schedule) else yr1_ds
            noi = float(cf.get("noi") or 0)
            after_ds = noi - ds
            dscr = noi / ds if ds else 0
            coc_val = float(returns["coc_by_year"][i]["coc"]) if i < len(returns.get("coc_by_year", [])) else 0
            lb = float(debt_schedule[i].get("end_balance") or 0) if i < len(debt_schedule) else 0

            bg = LIGHT_ROW if i % 2 == 0 else WHITE
            pdf._draw_rect(cf_x, cf_y, cf_w, row_height, bg)

            row_data = [
                (str(cf.get("year_num", i + 1)), 8, "L"),
                (f"{cf['start']} to {cf['end']}", 38, "L"),
                (_fm(noi), 24, "R"),
                (_fm(ds), 24, "R"),
                (_fm(after_ds), 24, "R"),
                (f"{dscr:.2f}x", 18, "R"),
                (f"{coc_val*100:.1f}%", 18, "R"),
                (_fm(lb), 26, "R"),
            ]
            hx = cf_x
            for val, cw, align in row_data:
                vc = (RED if after_ds < 0 and val == _fm(after_ds) else
                      GREEN if after_ds > 0 and val == _fm(after_ds) else TEXT_DARK)
                pdf.set_xy(hx + 1, cf_y + 0.6)
                pdf.set_font("Helvetica", "", 7)
                pdf._text_color(vc)
                pdf.cell(cw - 1, row_height - 0.5, val, align=align)
                hx += cw
            cf_y += row_height

    # ── FOOTER ────────────────────────────────────────────────────────────────
    pdf._draw_rect(0, PH - 6, PW, 6, DARK_BG)
    pdf.set_xy(PAD, PH - 5)
    pdf.set_font("Helvetica", "", 6.5)
    pdf._text_color(TEXT_MID)
    pdf.cell(PW / 2, 4,
             "This report is for analysis purposes only. Not a guarantee of future performance.", align="L")
    pdf.set_xy(PW / 2, PH - 5)
    pdf._text_color(ACCENT)
    pdf.cell(PW / 2 - PAD, 4, "CRE Analyzer", align="R")

    return bytes(pdf.output())
