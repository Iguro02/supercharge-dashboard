"""
simulator.py — Background data simulator.
Generates realistic solar + EV telemetry every 30 seconds.
Supports fault injection for anomaly testing.
"""
import random
import math
from datetime import datetime, timezone

import database as db

# Track which sites have an injected fault active
_faulted_sites: set = set()

# Site capacity reference (kWp) — fallback if not in DB
SITE_CAPACITY = {
    "11111111-1111-1111-1111-111111111111": 8.0,
    "22222222-2222-2222-2222-222222222222": 5.5,
    "33333333-3333-3333-3333-333333333333": 30.0,
}


def inject_fault(site_id: str):
    """Called by /api/debug/inject-fault — makes one site produce ~40% below expected."""
    _faulted_sites.add(site_id)


def clear_fault(site_id: str):
    _faulted_sites.discard(site_id)


def _irradiance_now() -> float:
    """Simulate Singapore irradiance based on time of day (kWh/m²)."""
    hour = datetime.now(timezone.utc).hour + 8  # SGT = UTC+8
    hour = hour % 24
    if hour < 6 or hour > 19:
        return 0.0
    # Bell curve peaking at noon
    peak = 4.8  # avg Singapore irradiance
    sigma = 3.5
    irr = peak * math.exp(-0.5 * ((hour - 12.5) / sigma) ** 2)
    # Add slight random noise
    irr += random.uniform(-0.2, 0.2)
    return max(0.0, round(irr, 3))


def _simulate_solar(site_id: str, solar_kwp: float) -> dict:
    """Generate one solar reading for a site."""
    irr = _irradiance_now()
    pr = random.uniform(0.75, 0.82)          # performance ratio
    expected_kw = solar_kwp * irr * pr

    if site_id in _faulted_sites:
        # Inject fault: output is 40-55% below expected
        actual_kw = expected_kw * random.uniform(0.45, 0.60)
    else:
        # Normal: ±8% variation
        actual_kw = expected_kw * random.uniform(0.92, 1.08)

    actual_kw = max(0.0, actual_kw)
    energy_kwh = actual_kw * (30 / 60)      # 30-second interval → kWh
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
        "anomaly_flag": False,       # anomaly.py fills this in
        "anomaly_severity": "OK",
    }


def _simulate_ev(site_id: str, charger_count: int):
    """Randomly start/end EV sessions."""
    hour = datetime.now(timezone.utc).hour + 8
    hour = hour % 24
    # Higher activity in evenings (17–22 SGT)
    prob_new_session = 0.3 if 17 <= hour <= 22 else 0.1

    sessions = []
    for i in range(charger_count):
        if random.random() < prob_new_session:
            duration_min = random.uniform(20, 120)
            energy_kwh = random.uniform(5, 45)
            revenue = round(energy_kwh * 0.50, 2)  # SGD 0.50/kWh
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
    from anomaly import score_reading  # import here to avoid circular import

    try:
        # Get all sites from DB
        all_sites_res = db.get_db().table("sites").select("id, solar_kwp, charger_count").execute()
        sites = all_sites_res.data
    except Exception as e:
        print(f"[Simulator] Could not fetch sites: {e}")
        return

    for site in sites:
        site_id = site["id"]
        solar_kwp = site.get("solar_kwp") or SITE_CAPACITY.get(site_id, 5.0)
        charger_count = site.get("charger_count") or 2

        # Solar reading
        reading = _simulate_solar(site_id, solar_kwp)

        # Score anomaly
        try:
            result = score_reading(reading)
            reading["anomaly_flag"] = result["anomaly"]
            reading["anomaly_severity"] = result["severity"]
        except Exception:
            pass  # model not trained yet — skip scoring

        db.insert_solar_reading(reading)

        # EV sessions (occasional)
        for session in _simulate_ev(site_id, charger_count):
            db.insert_ev_session(session)

    print(f"[Simulator] Tick at {datetime.now(timezone.utc).strftime('%H:%M:%S')} — {len(sites)} sites updated")