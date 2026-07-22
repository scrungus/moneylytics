# moneylytics

Personal spending analytics dashboard fed by an [Emma](https://emma-app.com)
auto-export Google Sheet. FastAPI + SQLAlchemy + ECharts, deployed on the
homelab k3s cluster as `moneylytics.lab`.

## How it works

```
Emma app ──► "Emma transactions" Google Sheet ──► sync (hot reload, TTL 5 min)
                                                     │
                              rules + Claude Haiku categorization
                                                     │
                                  Postgres (CNPG) / SQLite (dev)
                                                     │
                     FastAPI + vanilla JS/ECharts dashboard ──► moneylytics.lab
```

- **Sync**: any API hit when data is older than `REFRESH_TTL` (default 300s)
  triggers a background re-pull of the sheet; the ↻ button forces one.
  Upserts are keyed on Emma's stable transaction IDs.
- **Categories**: Emma's own categories are the baseline. The vague
  `General` bucket is refined via a merchant→category rules table; merchants
  with no rule are batched to Claude Haiku once, and the answer is stored as
  a rule. Manual overrides (editable in the Transactions tab) always win and
  can be applied per-merchant.
- **Insights**: per-month digest written by Claude Sonnet, cached in the DB.
- **Subscriptions**: recurring-payment detection from cadence + amount.

## Configuration (env / .env)

| Var | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL; defaults to `sqlite:///data/moneylytics.db` |
| `GOOGLE_SA_JSON` + `SHEET_ID` | Service-account JSON path + sheet ID (preferred source) |
| `SHEET_CSV_URL` | Published-CSV fallback source |
| `EMMA_XLSX` | Local xlsx export (dev seeding) |
| `SHEET_TAB` | Sheet tab name, default `Primary` |
| `REFRESH_TTL` | Seconds before data is considered stale, default 300 |
| `ANTHROPIC_API_KEY` | Enables Haiku categorization + Sonnet insights |

## Dev

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt openpyxl
EMMA_XLSX=data/emma.xlsx .venv/bin/python scripts/seed_dev.py
.venv/bin/uvicorn app.main:app --port 8321
```

## Deploy

```bash
podman build -t registry.lab/moneylytics:latest .
podman push --tls-verify=false registry.lab/moneylytics:latest
# chart lives in ~/homelab/helm/moneylytics — push there and ArgoCD does the rest
```
