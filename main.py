"""
main.py — FastAPI application entry point.
All API routes, background scheduler, static file serving.
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

import database as db
import auth
import simulator
import anomaly
import digest
import pdf_report

load_dotenv()

# ── Scheduler ────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed users on startup
    _seed_users()
    # Fetch real Singapore irradiance from NASA POWER API
    simulator.fetch_nasa_irradiance()
    # Start simulation every 30 seconds
    scheduler.add_job(simulator.run_simulation_tick, "interval", seconds=30, id="sim")
    # Retrain anomaly model every 10 minutes
    scheduler.add_job(anomaly.retrain_from_db, "interval", minutes=10, id="retrain")
    # Refresh NASA data daily (irradiance changes by month)
    scheduler.add_job(simulator.fetch_nasa_irradiance, "interval", hours=24, id="nasa")
    scheduler.start()
    # Initial tick immediately
    simulator.run_simulation_tick()
    yield
    scheduler.shutdown()


app = FastAPI(title="SuperCharge SG Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _seed_users():
    """Create the two demo users if they don't exist yet."""
    users = [
        ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "clientA@test.com", "passwordA"),
        ("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "clientB@test.com", "passwordB"),
    ]
    for org_id, email, password in users:
        existing = db.get_user_by_email(email)
        if not existing:
            db.create_user(org_id, email, auth.hash_password(password))
            print(f"[Seed] Created user {email}")


# ── Auth routes ───────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/login")
def login(req: LoginRequest):
    user = db.get_user_by_email(req.email)
    if not user or not auth.verify_password(req.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = auth.create_access_token(user["id"], user["org_id"])
    return {"access_token": token, "token_type": "bearer"}


# ── Sites ─────────────────────────────────────────────────────────────────────

@app.get("/api/sites")
def list_sites(org_id: str = Depends(auth.get_current_org)):
    return db.get_sites_for_org(org_id)


# ── Solar data ────────────────────────────────────────────────────────────────

@app.get("/api/solar/{site_id}/latest")
def solar_latest(site_id: str, org_id: str = Depends(auth.get_current_org)):
    # Enforce tenant isolation
    site = db.get_site(site_id, org_id)
    if not site:
        raise HTTPException(status_code=403, detail="Access denied")
    readings = db.get_latest_solar(site_id, limit=48)
    return readings


@app.get("/api/solar/{site_id}/anomalies")
def solar_anomalies(site_id: str, org_id: str = Depends(auth.get_current_org)):
    site = db.get_site(site_id, org_id)
    if not site:
        raise HTTPException(status_code=403, detail="Access denied")
    return db.get_anomalies(site_id, limit=20)


# ── EV data ───────────────────────────────────────────────────────────────────

@app.get("/api/ev/{site_id}/sessions")
def ev_sessions(site_id: str, org_id: str = Depends(auth.get_current_org)):
    site = db.get_site(site_id, org_id)
    if not site:
        raise HTTPException(status_code=403, detail="Access denied")
    return db.get_ev_sessions(site_id, limit=20)


# ── ECIS tracker ─────────────────────────────────────────────────────────────

@app.get("/api/solar/{site_id}/ecis")
def ecis_credits(site_id: str, org_id: str = Depends(auth.get_current_org)):
    site = db.get_site(site_id, org_id)
    if not site:
        raise HTTPException(status_code=403, detail="Access denied")
    solar_data = db.get_solar_summary(site_id, days=30)
    total_kwh = sum(r.get("energy_kwh", 0) or 0 for r in solar_data)
    exported_kwh = total_kwh * 0.30        # assume 30% exported
    credits_sgd = exported_kwh * 0.218    # ECIS rate SGD 0.218/kWh
    return {
        "total_solar_kwh": round(total_kwh, 2),
        "exported_kwh": round(exported_kwh, 2),
        "ecis_rate": 0.218,
        "credits_sgd": round(credits_sgd, 2),
    }


# ── AI Weekly Digest ──────────────────────────────────────────────────────────

@app.get("/api/digest/{site_id}")
def get_digest(site_id: str, org_id: str = Depends(auth.get_current_org)):
    site = db.get_site(site_id, org_id)
    if not site:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get org name
    org_res = db.get_db().table("organisations").select("name").eq("id", org_id).execute()
    org_name = org_res.data[0]["name"] if org_res.data else "Client"

    data = digest.build_digest_data(site_id, site["name"], org_name)
    text = digest.generate_weekly_digest(site["name"], org_name, data)
    return {"digest": text, "data": data}


# ── PDF Report ────────────────────────────────────────────────────────────────

@app.get("/api/report/{site_id}/pdf")
def download_pdf(site_id: str, org_id: str = Depends(auth.get_current_org)):
    site = db.get_site(site_id, org_id)
    if not site:
        raise HTTPException(status_code=403, detail="Access denied")

    org_res = db.get_db().table("organisations").select("name").eq("id", org_id).execute()
    org_name = org_res.data[0]["name"] if org_res.data else "Client"

    solar_data = db.get_solar_summary(site_id, days=30)
    ev_data = db.get_ev_summary(site_id, days=30)
    anomaly_data = db.get_anomalies(site_id, limit=20)

    solar_kwh = sum(r.get("energy_kwh", 0) or 0 for r in solar_data)
    ev_kwh = sum(e.get("energy_kwh", 0) or 0 for e in ev_data)
    ev_sessions = len([e for e in ev_data if e.get("status") == "Charging"])
    exported_kwh = solar_kwh * 0.30
    ecis_credits = exported_kwh * 0.218

    pdf_bytes = pdf_report.generate_monthly_report(
        client_name=org_name,
        site_name=site["name"],
        solar_kwh=round(solar_kwh, 1),
        ev_sessions=ev_sessions,
        ev_kwh=round(ev_kwh, 1),
        ecis_credits=round(ecis_credits, 2),
        anomaly_log=anomaly_data,
    )

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    filename = f"supercharge-report-{site['name'].replace(' ', '-')}-{month}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ── Debug / Eval helpers ──────────────────────────────────────────────────────

@app.post("/api/debug/inject-fault/{site_id}")
def inject_fault(site_id: str, org_id: str = Depends(auth.get_current_org)):
    """Evaluator uses this to trigger a fault for anomaly detection testing."""
    site = db.get_site(site_id, org_id)
    if not site:
        raise HTTPException(status_code=403, detail="Access denied")
    simulator.inject_fault(site_id)
    return {"status": "fault injected", "site_id": site_id}


@app.post("/api/debug/clear-fault/{site_id}")
def clear_fault(site_id: str, org_id: str = Depends(auth.get_current_org)):
    site = db.get_site(site_id, org_id)
    if not site:
        raise HTTPException(status_code=403, detail="Access denied")
    simulator.clear_fault(site_id)
    # Also clear anomaly records from DB so the log resets visually
    try:
        db.get_db().table("solar_readings") \
            .update({"anomaly_flag": False, "anomaly_severity": "OK"}) \
            .eq("site_id", site_id) \
            .eq("anomaly_flag", True) \
            .execute()
    except Exception as e:
        print(f"[ClearFault] Could not reset anomaly records: {e}")
    return {"status": "fault cleared", "site_id": site_id}


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/nasa/irradiance")
def nasa_irradiance():
    """Returns the current NASA irradiance data being used by the simulator."""
    return {
        "source": "NASA POWER API",
        "location": "Singapore (lat=1.3521, lon=103.8198)",
        "monthly_avg_kwh_m2_day": simulator._NASA_MONTHLY_IRR,
        "current_month": datetime.now(timezone.utc).month,
        "current_baseline": simulator._NASA_MONTHLY_IRR.get(datetime.now(timezone.utc).month),
    }


# ── Static files (frontend) ───────────────────────────────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")
