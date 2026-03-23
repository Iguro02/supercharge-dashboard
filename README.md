# SuperCharge SG — Smart Energy Dashboard
### Challenge 2 Submission · SuperCharge SG Build Challenge 2026

---

## Live URL
> Replace with your Railway deployment URL after deploy

## Demo Credentials
| Account | Email | Password | Sites |
|---|---|---|---|
| Client A | clientA@test.com | passwordA | Sunshine Condo Block A, Block B |
| Client B | clientB@test.com | passwordB | GreenPark Mall Rooftop |

---

## Architecture

```
Browser (Plain HTML + JS + Chart.js)
        │  REST polling every 30s
        ▼
FastAPI (Python 3.11)
├── /api/login          → JWT auth
├── /api/sites          → org-scoped site list
├── /api/solar/:id/*    → solar readings, anomalies, ECIS
├── /api/ev/:id/*       → EV sessions
├── /api/digest/:id     → Gemini AI weekly digest
├── /api/report/:id/pdf → ReportLab monthly PDF
└── /api/debug/*        → fault inject (eval only)
        │
        ├── Supabase (PostgreSQL) — multi-tenant data store
        ├── APScheduler — sim tick every 30s, retrain every 10min
        ├── Isolation Forest (scikit-learn) — anomaly detection
        └── Gemini 1.5 Flash — weekly digest generation
```

## Data Model

```sql
organisations  (id, name)
users          (id, org_id, email, hashed_password)
sites          (id, org_id, name, solar_kwp, charger_count)
solar_readings (id, site_id, ts, power_kw, energy_kwh, irradiance,
                temp_c, expected_kw, performance_ratio,
                anomaly_flag, anomaly_severity)
ev_sessions    (id, site_id, charger_id, start_ts, end_ts,
                energy_kwh, revenue_sgd, status)
```

All queries are scoped by `org_id` from the JWT. Cross-tenant access returns **HTTP 403**.

---

## Anomaly Detection Methodology

**Model**: scikit-learn `IsolationForest` (contamination=0.05)

**Features used**:
- `performance_ratio` — actual/expected output ratio
- `actual_vs_expected_pct` — normalised output deviation
- `temp_c` — panel temperature
- `irradiance` — solar irradiance (kWh/m²)

**Flagging logic**:
1. If irradiance < 0.3 kWh/m² → skip (nighttime)
2. If actual output < 85% of expected → flag (rule-based, always reliable)
3. Isolation Forest scores remaining readings → flag outliers

**Severity**:
- `CRITICAL` — drop > 35% below expected
- `WARNING` — drop 15–35% below expected
- `OK` — normal operation

**False positive mitigation**: Nighttime readings are excluded. Model is retrained every 10 minutes on the latest 500 readings.

---

## ECIS Credit Calculation

```
ECIS Credits (SGD) = exported_kWh × 0.218

Where:
  exported_kWh = total_solar_kWh × 0.30
  (30% export assumption — typical Singapore residential/commercial)
  Rate: SGD 0.218/kWh (SP Group Enhanced Central Intermediary Scheme)
```

Source: Section B3 of SuperCharge SG Knowledge Base. Rate verified against SP Group ECIS documentation.

---

## Multi-Tenant Design

1. Login returns a JWT containing `org_id`
2. Every API endpoint calls `get_current_org(token)` → extracts `org_id`
3. All DB queries filter by `org_id` (sites) or `site_id IN (sites WHERE org_id=...)` (readings)
4. `get_site(site_id, org_id)` returns `None` if site doesn't belong to org → endpoint returns 403

**Test it**: Login as Client A, note a site_id. Login as Client B. Try `GET /api/solar/<clientA_site_id>/latest` with Client B's token → returns 403.

---

## NASA POWER API Integration

Solar irradiance baseline uses the simulator with Singapore coordinates:
- Latitude: 1.3521, Longitude: 103.8198
- Expected daily peak: 4.5–5.2 kWh/m²/day
- PR (Performance Ratio): 0.75–0.82

For production, replace `simulator._irradiance_now()` with live NASA API data:
```
https://power.larc.nasa.gov/api/temporal/monthly/point
?parameters=ALLSKY_SFC_SW_DWN&community=RE
&longitude=103.8198&latitude=1.3521&start=2024&end=2024&format=JSON
```

---

## Local Setup

```bash
git clone <your-repo>
cd supercharge-dashboard
pip install -r requirements.txt
cp .env.example .env
# Fill in SUPABASE_URL, SUPABASE_KEY, JWT_SECRET, GEMINI_API_KEY
```

Run Supabase schema:
- Go to your Supabase project → SQL Editor
- Paste and run the contents of `schema.sql`

```bash
uvicorn main:app --reload --port 8000
# Visit http://localhost:8000/login.html
```

---

## Railway Deployment

```bash
# Install Railway CLI
npm install -g @railway/cli
railway login
railway init
railway up
# Add env vars in Railway dashboard → Variables
```

Required environment variables:
```
SUPABASE_URL=
SUPABASE_KEY=
JWT_SECRET=
GEMINI_API_KEY=
```

---

## Evaluator: Anomaly Testing

1. Login as either client
2. Select any site
3. Click **"⚠ Inject Fault"** button
4. Wait 30 seconds (one simulation tick)
5. The anomaly log will show a **CRITICAL** entry with actual vs expected output
6. The chart will show a red triangle marker at the anomaly point
7. Click **"✓ Clear Fault"** to restore normal operation

---

## Known Limitations

- ECIS export % is estimated at 30% (typical for SG); a production system would read from a smart meter
- NASA POWER API is not called live in the simulator — irradiance is modelled by time-of-day curve
- Email delivery for weekly digest requires SMTP config; digest text is returned via API and displayed in modal
- Anomaly model requires ~10 readings before it trains (fills in ~5 minutes of simulation)
