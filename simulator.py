"""
simulator.py — Background data simulator.
Generates realistic solar + EV telemetry every 30 seconds.
Irradiance baseline sourced from NASA POWER API (Singapore coords).
Supports fault injection for anomaly testing.
"""
import random
import math
from datetime import datetime, timezone

import httpx
import database as db

# Track which sites have an injected fault active
_faulted_sites: set = set()

# Site capacity reference (kWp) — fallback if not in DB
SITE_CAPACITY = {
    "11111111-1111-1111-1111-111111111111": 8.0,
    "22222222-2222-2222-2222-222222222222": 5.5,
    "33333333-3333-3333-3333-333333333333": 30.0,
}

# NASA POWER API — monthly average irradiance for Singapore (kWh/m2/day)
# Fetched once on startup, cached here. Keyed by month number (1-12).
# Fallback values based on known Singapore averages if API unavailable.
_NASA_MONTHLY_IRR = {
    1: 4.51, 2: 4.89, 3: 5.12, 4: 5.08,
    5: 4.97, 6: 4.82, 7: 4.93, 8: 4.88,
    9: 4.71, 10: 4.62, 11: 4.21, 12: 4.18,
}


def fetch_nasa_irradiance():
    """
    Fetch real monthly irradiance from NASA POWER API for Singapore.
    Singapore coords: lat=1.3521, lon=103.8198
    Updates _NASA_MONTHLY_IRR in place. Called once on startup.
    """
    global _NASA_MONTHLY_IRR
    url = "https://power.larc.nasa.gov/api/temporal/monthly/point"
    params = {
        "parameters": "ALLSKY_SFC_SW_DWN",
        "community": "RE",
        "longitude": 103.8198,
        "latitude": 1.3521,
        "start": "2020",
        "end": "2023",
        "format": "JSON",
    }
    try:
        print("[NASA] Fetching Singapore irradiance data...")
        r = httpx.get(url, params=params, timeout=15)
        data = r.json()
        monthly = data["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
        month_totals = {}
        month_counts = {}
        for key, val in monthly.items():
            if val == -999:
                continue
            month_num = int(key[4:6])
            if month_num < 1 or month_num > 12:
                continue
            month_totals[month_num] = month_totals.get(month_num, 0) + val
            month_counts[month_num] = month_counts.get(month_num, 0) + 1
        for m in range(1, 13):
            if m in month_totals and month_counts[m] > 0:
                _NASA_MONTHLY_IRR[m] = round(month_totals[m] / month_counts[m], 3)
        print(f"[NASA] Irradiance data loaded: {_NASA_MONTHLY_IRR}")
    except Exception as e:
        print(f"[NASA] API fetch failed, using fallback values: {e}")


def inject_fault(site_id: str):
    """Called by /api/debug/inject-fault."""
    _faulted_sites.add(site_id)


def clear_fault(site_id: str):
    _faulted_sites.discard(site_id)


def _irradiance_now() -> float:
    """
    Calculate current irradiance (kWh/m2) using:
    - NASA POWER monthly average as the daily peak baseline
    - Bell curve scaled to time of day (SGT)
    - Minimum of 1.0 enforced so charts always show data
    """
    hour = (datetime.now(timezone.utc).hour + 8) % 24
    month = datetime.now(timezone.utc).month
    daily_avg = _NASA_MONTHLY_IRR.get(month, 4.8)
    sigma = 3.5
    irr = daily_avg * math.exp(-0.5 * ((hour - 12.5) / sigma) ** 2)
    irr += random.uniform(-0.15, 0.15)
    return max(1.0, round(irr, 3))


def _simulate_solar(site_id: str, solar_kwp: float) -> dict:
    """Generate one solar reading for a site."""
    irr = _irradiance_now()
    pr = random.uniform(0.75, 0.82)
    expected_kw = solar_kwp * irr * pr

    if site_id in _faulted_sites:
        actual_kw = expected_kw * random.uniform(0.45, 0.60)
    else:
        actual_kw = expected_kw * random.uniform(0.92, 1.08)

    actual_kw = max(0.0, actual_kw)
    energy_kwh = actual_kw * (30 / 60)
    temp_c = random.uniform(28.0, 38.0)
    perf_ratio = (actual_kw / expected_kw) if expected_kw > 0 else 1.0

    return {
        "site_id": site_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "power_kw": round(actual_kw, 3),
        "energy_kwh": round(energy_kwh, 4),
        "irradiance": irr,
        "temp_c": round(temp_c, 1),
        "expected_kw": round(expected_kw, 3),
        "performance_ratio": round(perf_ratio, 4),
        "anomaly_flag": False,
        "anomaly_severity": "OK",
    }


def _simulate_ev(site_id: str, charger_count: int):
    """Randomly start/end EV sessions."""
    hour = (datetime.now(timezone.utc).hour + 8) % 24
    prob_new_session = 0.3 if 17 <= hour <= 22 else 0.1

    sessions = []
    for i in range(charger_count):
        if random.random() < prob_new_session:
            duration_min = random.uniform(20, 120)
            energy_kwh = random.uniform(5, 45)
            revenue = round(energy_kwh * 0.50, 2)
            start = datetime.now(timezone.utc)
            end = start.replace(minute=(start.minute + int(duration_min)) % 60)
            sessions.append({
                "site_id": site_id,
                "charger_id": f"CHG-{site_id[:4].upper()}-{i+1:02d}",
                "start_ts": start.isoformat(),
                "end_ts": end.isoformat(),
                "energy_kwh": round(energy_kwh, 2),
                "revenue_sgd": revenue,
                "status": "Charging",
            })
    return sessions


def run_simulation_tick():
    """Called every 30 seconds by APScheduler in main.py."""
    from anomaly import score_reading

    try:
        all_sites_res = db.get_db().table("sites").select("id, solar_kwp, charger_count").execute()
        sites = all_sites_res.data
    except Exception as e:
        print(f"[Simulator] Could not fetch sites: {e}")
        return

    for site in sites:
        site_id = site["id"]
        solar_kwp = site.get("solar_kwp") or SITE_CAPACITY.get(site_id, 5.0)
        charger_count = site.get("charger_count") or 2

        reading = _simulate_solar(site_id, solar_kwp)

        try:
            result = score_reading(reading)
            reading["anomaly_flag"] = bool(result["anomaly"])
            reading["anomaly_severity"] = str(result["severity"])
        except Exception:
            reading["anomaly_flag"] = False
            reading["anomaly_severity"] = "OK"

        db.insert_solar_reading(reading)

        for session in _simulate_ev(site_id, charger_count):
            db.insert_ev_session(session)

    print(f"[Simulator] Tick at {datetime.now(timezone.utc).strftime('%H:%M:%S')} — {len(sites)} sites updated")
