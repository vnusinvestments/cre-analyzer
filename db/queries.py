"""CRUD operations for all tables."""

from datetime import datetime
from typing import Optional
from db.schema import get_conn, DEFAULT_DD_ITEMS


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


# ── Deals ─────────────────────────────────────────────────────────────────────

def get_all_deals() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM deals ORDER BY updated_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_deal(deal_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    return _row_to_dict(row) if row else None


def upsert_deal(data: dict) -> int:
    """Insert or update a deal. Returns deal_id."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    deal_id = data.get("id")
    with get_conn() as conn:
        if deal_id:
            conn.execute(
                """UPDATE deals SET
                    name=?, address=?, city=?, state=?, tenant=?,
                    property_type=?, building_sf=?, land_acres=?, year_built=?,
                    stage=?, updated_at=?
                WHERE id=?""",
                (
                    data.get("name", ""),
                    data.get("address", ""),
                    data.get("city", ""),
                    data.get("state", ""),
                    data.get("tenant", ""),
                    data.get("property_type", "NNN Retail"),
                    data.get("building_sf", 0),
                    data.get("land_acres", 0),
                    data.get("year_built"),
                    data.get("stage", "Screening"),
                    now,
                    deal_id,
                ),
            )
            conn.commit()
        else:
            cur = conn.execute(
                """INSERT INTO deals
                    (name, address, city, state, tenant,
                     property_type, building_sf, land_acres, year_built, stage)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("name", "New Deal"),
                    data.get("address", ""),
                    data.get("city", ""),
                    data.get("state", ""),
                    data.get("tenant", ""),
                    data.get("property_type", "NNN Retail"),
                    data.get("building_sf", 0),
                    data.get("land_acres", 0),
                    data.get("year_built"),
                    data.get("stage", "Screening"),
                ),
            )
            deal_id = cur.lastrowid
            conn.commit()
    return deal_id


def delete_deal(deal_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM deals WHERE id=?", (deal_id,))
        conn.commit()


# ── Scenarios ─────────────────────────────────────────────────────────────────

_SCENARIO_COLS = (
    "deal_id,name,is_default,base_annual_rent,lease_start,lease_expiration,"
    "escalation_type,escalation_pct,escalation_years,fixed_steps_json,"
    "renewal_count,renewal_years,renewal_rent_pct,lease_type,"
    "vacancy_loss_pct,capital_reserve_per_sf,roof_reserve_per_sf,"
    "mgmt_pct,non_recoverable,"
    "price,closing_costs_pct,analysis_start,hold_years,prelease_cost,"
    "ltv,rate,amort_years,io_months,loan_fee_pct,"
    "exit_cap,sale_costs_pct,target_irr,"
    "vacancy_start_year,downtime_months,downtime_costs_per_sf,"
    "re_lease_rent_per_sf,ti_per_sf,lc_pct"
)

_SCENARIO_PLACEHOLDERS = ",".join("?" * len(_SCENARIO_COLS.split(",")))


def get_scenarios(deal_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scenarios WHERE deal_id=? ORDER BY is_default DESC, id ASC",
            (deal_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_scenario(scenario_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM scenarios WHERE id=?", (scenario_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_default_scenario(deal_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM scenarios WHERE deal_id=? ORDER BY is_default DESC, id ASC LIMIT 1",
            (deal_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def upsert_scenario(data: dict) -> int:
    """Insert or update a scenario. Returns scenario_id."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sid = data.get("id")
    with get_conn() as conn:
        if sid:
            conn.execute(
                """UPDATE scenarios SET
                    name=?, is_default=?,
                    base_annual_rent=?, lease_start=?, lease_expiration=?,
                    escalation_type=?, escalation_pct=?, escalation_years=?,
                    fixed_steps_json=?, renewal_count=?, renewal_years=?, renewal_rent_pct=?,
                    lease_type=?,
                    vacancy_loss_pct=?, capital_reserve_per_sf=?, roof_reserve_per_sf=?,
                    mgmt_pct=?, non_recoverable=?,
                    price=?, closing_costs_pct=?, analysis_start=?, hold_years=?, prelease_cost=?,
                    ltv=?, rate=?, amort_years=?, io_months=?, loan_fee_pct=?,
                    exit_cap=?, sale_costs_pct=?, target_irr=?,
                    vacancy_start_year=?, downtime_months=?, downtime_costs_per_sf=?,
                    re_lease_rent_per_sf=?, ti_per_sf=?, lc_pct=?,
                    updated_at=?
                WHERE id=?""",
                (
                    data.get("name", "Asking"),
                    data.get("is_default", 1),
                    data.get("base_annual_rent"),
                    data.get("lease_start"),
                    data.get("lease_expiration"),
                    data.get("escalation_type", "flat"),
                    data.get("escalation_pct", 0.0),
                    data.get("escalation_years", 5),
                    data.get("fixed_steps_json", "[]"),
                    data.get("renewal_count", 0),
                    data.get("renewal_years", 5),
                    data.get("renewal_rent_pct", 0.0),
                    data.get("lease_type", "absolute_nnn"),
                    data.get("vacancy_loss_pct", 0.0),
                    data.get("capital_reserve_per_sf", 0.0),
                    data.get("roof_reserve_per_sf", 0.0),
                    data.get("mgmt_pct", 0.0),
                    data.get("non_recoverable", 0.0),
                    data.get("price"),
                    data.get("closing_costs_pct", 0.0),
                    data.get("analysis_start"),
                    data.get("hold_years", 10),
                    data.get("prelease_cost", 0.0),
                    data.get("ltv", 0.65),
                    data.get("rate", 0.07),
                    data.get("amort_years", 25),
                    data.get("io_months", 0),
                    data.get("loan_fee_pct", 0.0),
                    data.get("exit_cap", 0.08),
                    data.get("sale_costs_pct", 0.0),
                    data.get("target_irr", 0.10),
                    data.get("vacancy_start_year", 11),
                    data.get("downtime_months", 12),
                    data.get("downtime_costs_per_sf", 3.0),
                    data.get("re_lease_rent_per_sf", 0.0),
                    data.get("ti_per_sf", 0.0),
                    data.get("lc_pct", 0.05),
                    now,
                    sid,
                ),
            )
            conn.commit()
        else:
            cur = conn.execute(
                f"""INSERT INTO scenarios ({_SCENARIO_COLS}) VALUES ({_SCENARIO_PLACEHOLDERS})""",
                (
                    data["deal_id"],
                    data.get("name", "Asking"),
                    data.get("is_default", 1),
                    data.get("base_annual_rent"),
                    data.get("lease_start"),
                    data.get("lease_expiration"),
                    data.get("escalation_type", "flat"),
                    data.get("escalation_pct", 0.0),
                    data.get("escalation_years", 5),
                    data.get("fixed_steps_json", "[]"),
                    data.get("renewal_count", 0),
                    data.get("renewal_years", 5),
                    data.get("renewal_rent_pct", 0.0),
                    data.get("lease_type", "absolute_nnn"),
                    data.get("vacancy_loss_pct", 0.0),
                    data.get("capital_reserve_per_sf", 0.0),
                    data.get("roof_reserve_per_sf", 0.0),
                    data.get("mgmt_pct", 0.0),
                    data.get("non_recoverable", 0.0),
                    data.get("price"),
                    data.get("closing_costs_pct", 0.0),
                    data.get("analysis_start"),
                    data.get("hold_years", 10),
                    data.get("prelease_cost", 0.0),
                    data.get("ltv", 0.65),
                    data.get("rate", 0.07),
                    data.get("amort_years", 25),
                    data.get("io_months", 0),
                    data.get("loan_fee_pct", 0.0),
                    data.get("exit_cap", 0.08),
                    data.get("sale_costs_pct", 0.0),
                    data.get("target_irr", 0.10),
                    data.get("vacancy_start_year", 11),
                    data.get("downtime_months", 12),
                    data.get("downtime_costs_per_sf", 3.0),
                    data.get("re_lease_rent_per_sf", 0.0),
                    data.get("ti_per_sf", 0.0),
                    data.get("lc_pct", 0.05),
                ),
            )
            sid = cur.lastrowid
            conn.commit()
    return sid


def clone_scenario(scenario_id: int, new_name: str) -> int:
    """Duplicate a scenario with a new name. Returns new scenario_id."""
    src = get_scenario(scenario_id)
    if not src:
        raise ValueError(f"Scenario {scenario_id} not found")
    new = dict(src)
    new.pop("id", None)
    new["name"] = new_name
    new["is_default"] = 0
    return upsert_scenario(new)


def delete_scenario(scenario_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM scenarios WHERE id=?", (scenario_id,))
        conn.commit()


# ── Due Diligence ──────────────────────────────────────────────────────────────

def get_dd_items(deal_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM due_diligence WHERE deal_id=? ORDER BY sort_order, id",
            (deal_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def ensure_dd_items(deal_id: int) -> None:
    """Seed the default checklist if this deal has no DD items yet."""
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM due_diligence WHERE deal_id=?", (deal_id,)
        ).fetchone()[0]
        if count == 0:
            for i, item in enumerate(DEFAULT_DD_ITEMS):
                conn.execute(
                    "INSERT INTO due_diligence (deal_id, item_name, sort_order) VALUES (?,?,?)",
                    (deal_id, item, i),
                )
            conn.commit()


def update_dd_item(item_id: int, status: str, notes: str, completed_date: Optional[str]) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE due_diligence SET status=?, notes=?, completed_date=? WHERE id=?",
            (status, notes, completed_date, item_id),
        )
        conn.commit()


def add_dd_item(deal_id: int, item_name: str) -> None:
    with get_conn() as conn:
        max_order = conn.execute(
            "SELECT MAX(sort_order) FROM due_diligence WHERE deal_id=?", (deal_id,)
        ).fetchone()[0] or 0
        conn.execute(
            "INSERT INTO due_diligence (deal_id, item_name, sort_order) VALUES (?,?,?)",
            (deal_id, item_name, max_order + 1),
        )
        conn.commit()


def delete_dd_item(item_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM due_diligence WHERE id=?", (item_id,))
        conn.commit()


# ── Notes ─────────────────────────────────────────────────────────────────────

def get_notes(deal_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM deal_notes WHERE deal_id=? ORDER BY created_at DESC",
            (deal_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def add_note(deal_id: int, content: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO deal_notes (deal_id, content) VALUES (?,?)",
            (deal_id, content),
        )
        conn.commit()


def delete_note(note_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM deal_notes WHERE id=?", (note_id,))
        conn.commit()
