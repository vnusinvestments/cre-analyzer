# CRE Deal Analyzer

Local web app for underwriting commercial real estate acquisitions, starting with single-tenant net lease (STNL) deals.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

## Test

```bash
pytest
```

## Project structure

```
engine/         Pure-Python calculation engine (no Streamlit imports)
  lease.py      Rent schedule from lease parameters
  expenses.py   Landlord expenses by lease type
  cashflow.py   Annual NOI
  valuation.py  Cap rate, price ladder, DCF
  debt.py       Loan amortization
  returns.py    IRR, equity multiple, cash-on-cash
  sensitivity.py Two-way grids
  downside.py   Tenant-goes-dark scenario
tests/
  test_walgreens_chester.py  Verification against known deal
app.py          Streamlit UI (Phase 2)
deals.db        SQLite database (created on first run)
```
