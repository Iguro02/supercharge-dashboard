# SuperCharge SG — Smart Energy Dashboard
### Challenge 2 Submission · SuperCharge SG Build Challenge 2026

---

## Live URL
> https://supercharge-dashboard-production-f3f5.up.railway.app/login.html

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
├── /api/nasa/irradiance → NASA data status
└── /api/debug/*        → fault inject (eval only)
        │
        ├── Supabase (PostgreSQL) — multi-tenant data store
        ├── APScheduler — sim tick every 30s, retrain every 10min, NASA refresh every 24h
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

**Model**: scikit-learn `IsolationForest` (contamination=0.02)

**Features used**:
- `performance_ratio` — actual/expected output ratio
- `actual_vs_expected_pct` — normalised output deviation
- `temp_c` — panel temperature
- `irradiance` — solar irradiance (kWh/m²)

**Flagging logic** (layered — rule-based first, ML second):
1. If irradiance < 0.1 kWh/m² → skip (essentially no sunlight)
2. If drop > 35% below expected → flag CRITICAL immediately (rule-based)
3. If drop > 20% below expected → flag WARNING immediately (rule-based)
4. If drop > 15% AND Isolation Forest also flags it → flag WARNING (ML-assisted)
5. Otherwise → OK

**Severity**:
- `CRITICAL` — drop > 35% below expected
- `WARNING` — drop 20–35% below expected
- `OK` — normal operation (includes natural ±8% variation)

**False positive mitigation**:
- Threshold set at 20% (not 15%) to avoid flagging normal day-to-day variation
- ML model only fires as a secondary check, never independently
- `contamination=0.02` means only the most extreme 2% of readings are flagged
- Model requires minimum 20 readings before training activates
- Model retrains every 10 minutes on the latest 500 readings

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

Irradiance baseline is fetched live from NASA POWER API on every server startup and refreshed every 24 hours.

- **Endpoint**: `https://power.larc.nasa.gov/api/temporal/monthly/point`
- **Location**: Singapore — Latitude: 1.3521, Longitude: 103.8198
- **Parameter**: `ALLSKY_SFC_SW_DWN` (surface solar irradiance, kWh/m²/day)
- **Years averaged**: 2020–2023
- **PR (Performance Ratio)**: 0.75–0.82 (typical Singapore install)

Monthly averages are used to scale the irradiance bell curve for the current month, so the simulation reflects real seasonal variation in Singapore's solar output (lowest in Nov/Dec, highest in Mar/Apr).

To verify NASA data is loaded on your live deployment:
```
GET /api/nasa/irradiance
```

If the NASA API is unreachable, the simulator falls back to hardcoded Singapore averages silently.

---

## Deployment

Deployed on **Railway Hobby plan** — server runs continuously with no idle spindown, ensuring the simulator ticks every 30 seconds reliably and data accumulates in Supabase without interruption.

Required environment variables set in Railway dashboard:
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
6. The solar chart will show a red triangle marker at the anomaly point
7. Click **"✓ Clear Fault"** to restore normal operation

---

## Known Limitations

- ECIS export % is estimated at 30% (typical for SG); a production system would read from a smart meter
- Email delivery for weekly digest requires SMTP config; digest text is returned via API and displayed in modal for the evaluator to copy
- Anomaly ML model requires ~20 readings before training activates (approximately 10 minutes after first startup); rule-based thresholds fire immediately from the first reading
