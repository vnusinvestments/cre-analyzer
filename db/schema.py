"""Database schema and initialization."""

import os
import sqlite3

DB_PATH = os.environ.get(
    'DATABASE_PATH',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deals.db")
)

STAGES = ["Screening", "Underwriting", "LOI", "Due Diligence", "Under Contract", "Closed", "Passed"]

LEASE_TYPES = ["absolute_nnn", "nnn", "nn", "gross"]
LEASE_TYPE_LABELS = {
    "absolute_nnn": "Absolute NNN",
    "nnn": "NNN",
    "nn": "NN",
    "gross": "Gross",
}

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS deals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    address     TEXT    DEFAULT '',
    city        TEXT    DEFAULT '',
    state       TEXT    DEFAULT '',
    tenant      TEXT    DEFAULT '',
    property_type TEXT  DEFAULT 'NNN Retail',
    building_sf REAL    DEFAULT 0,
    land_acres  REAL    DEFAULT 0,
    year_built  INTEGER,
    stage       TEXT    DEFAULT 'Screening',
    created_at  TEXT    DEFAULT (datetime('now','localtime')),
    updated_at  TEXT    DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS scenarios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id         INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL DEFAULT 'Asking',
    is_default      INTEGER DEFAULT 1,
    -- Lease
    base_annual_rent REAL,
    lease_start     TEXT,
    lease_expiration TEXT,
    escalation_type TEXT    DEFAULT 'flat',
    escalation_pct  REAL    DEFAULT 0.0,
    escalation_years INTEGER DEFAULT 5,
    fixed_steps_json TEXT   DEFAULT '[]',
    renewal_count   INTEGER DEFAULT 0,
    renewal_years   INTEGER DEFAULT 5,
    renewal_rent_pct REAL   DEFAULT 0.0,
    lease_type      TEXT    DEFAULT 'absolute_nnn',
    -- Expenses
    vacancy_loss_pct        REAL DEFAULT 0.0,
    capital_reserve_per_sf  REAL DEFAULT 0.0,
    roof_reserve_per_sf     REAL DEFAULT 0.0,
    mgmt_pct                REAL DEFAULT 0.0,
    non_recoverable         REAL DEFAULT 0.0,
    -- Purchase
    price               REAL,
    closing_costs_pct   REAL DEFAULT 0.0,
    analysis_start      TEXT,
    hold_years          INTEGER DEFAULT 10,
    prelease_cost       REAL DEFAULT 0.0,
    -- Debt
    ltv         REAL    DEFAULT 0.65,
    rate        REAL    DEFAULT 0.07,
    amort_years INTEGER DEFAULT 25,
    io_months   INTEGER DEFAULT 0,
    loan_fee_pct REAL   DEFAULT 0.0,
    -- Exit
    exit_cap        REAL DEFAULT 0.08,
    sale_costs_pct  REAL DEFAULT 0.0,
    target_irr      REAL DEFAULT 0.10,
    -- Downside
    vacancy_start_year      INTEGER DEFAULT 11,
    downtime_months         INTEGER DEFAULT 12,
    downtime_costs_per_sf   REAL    DEFAULT 3.0,
    re_lease_rent_per_sf    REAL    DEFAULT 0.0,
    ti_per_sf               REAL    DEFAULT 0.0,
    lc_pct                  REAL    DEFAULT 0.05,
    -- Timestamps
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS due_diligence (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id         INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    item_name       TEXT    NOT NULL,
    status          TEXT    DEFAULT 'open',
    notes           TEXT    DEFAULT '',
    completed_date  TEXT,
    sort_order      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS deal_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id     INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    content     TEXT    NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now','localtime'))
);
"""

DEFAULT_DD_ITEMS = [
    "Lease + all amendments",
    "Estoppel certificate",
    "Guarantor entity / financials",
    "Termination rights review",
    "ROFR / ROFO review",
    "Phase I environmental",
    "Title commitment + survey",
    "Zoning letter / certificate",
    "Roof / HVAC / parking condition report",
    "Insurance review",
    "Property tax history (5 years)",
    "Rent comps",
    "Sales comps",
    "Loan quote / term sheet",
]


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_SQL)
    # Migrations for columns added after initial schema
    for col, definition in [
        ("prelease_cost", "REAL DEFAULT 0.0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE scenarios ADD COLUMN {col} {definition}")
            conn.commit()
        except Exception:
            pass  # Column already exists
    conn.commit()
    conn.close()
