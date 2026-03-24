"""
digest.py — Weekly energy digest using Gemini API.
Generates a plain-English summary per client site.
"""
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))


def generate_weekly_digest(site_name: str, client_name: str, data: dict) -> str:
    """
    Generate a professional weekly energy digest.

    data keys:
        solar_kwh       - total solar generated this week
        expected_kwh    - expected based on irradiance
        ev_sessions     - number of EV charging sessions
        ev_kwh          - total EV energy delivered
        ecis_credits    - SGD earned via ECIS export
        anomaly_count   - number of anomalies flagged
        anomaly_details - string description of anomalies
        co2_kg          - CO2 saved (solar_kwh * 0.4233 kg/kWh SG grid factor)
    """
    model = genai.GenerativeModel("gemini-2.5-flash")

    prompt = f"""You are the energy reporting assistant for SuperCharge SG, a Singapore clean energy company.

Write a professional weekly energy digest for:
Client: {client_name}
Site: {site_name}
Week ending: {data.get('week_end', 'this week')}

PERFORMANCE DATA:
- Solar generated: {data.get('solar_kwh', 0):.1f} kWh (expected: {data.get('expected_kwh', 0):.1f} kWh)
- EV sessions: {data.get('ev_sessions', 0)} sessions, {data.get('ev_kwh', 0):.1f} kWh delivered
- ECIS export credits earned: SGD {data.get('ecis_credits', 0):.2f}
- Anomalies detected: {data.get('anomaly_count', 0)} ({data.get('anomaly_details', 'none')})
- CO2 saved: {data.get('co2_kg', 0):.1f} kg

Write exactly 3 short paragraphs:
1. Overall performance summary (compare actual vs expected solar, mention EV activity)
2. Anomaly findings and recommended actions (if none, say systems running normally)
3. Savings and sustainability highlight (ECIS credits, CO2 saved, equivalent trees planted)

Requirements: Under 180 words total. Plain English. No bullet points. No jargon. Professional but warm tone.
Do not add any heading or subject line — just the 3 paragraphs."""

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"[Digest generation failed: {e}]"


def build_digest_data(site_id: str, site_name: str, org_name: str) -> dict:
    """Pull data from DB and prepare digest input."""
    import database as db
    from datetime import datetime, timezone

    solar_data = db.get_solar_summary(site_id, days=7)
    ev_data = db.get_ev_summary(site_id, days=7)

    solar_kwh = sum(r.get("energy_kwh", 0) or 0 for r in solar_data)
    # Expected: use a simple average baseline
    expected_kwh = solar_kwh * 1.05  # rough baseline — in prod use NASA irradiance

    ev_sessions = len([e for e in ev_data if e.get("status") == "Charging"])
    ev_kwh = sum(e.get("energy_kwh", 0) or 0 for e in ev_data)

    anomalies = [r for r in solar_data if r.get("anomaly_flag")]
    anomaly_count = len(anomalies)

    # ECIS: assume 30% of solar is exported
    exported_kwh = solar_kwh * 0.30
    ecis_credits = exported_kwh * 0.218  # SGD 0.218/kWh

    # CO2 saved: Singapore grid factor ~0.4233 kg CO2/kWh
    co2_kg = solar_kwh * 0.4233

    return {
        "site_name": site_name,
        "client_name": org_name,
        "week_end": datetime.now(timezone.utc).strftime("%d %b %Y"),
        "solar_kwh": round(solar_kwh, 1),
        "expected_kwh": round(expected_kwh, 1),
        "ev_sessions": ev_sessions,
        "ev_kwh": round(ev_kwh, 1),
        "ecis_credits": round(ecis_credits, 2),
        "anomaly_count": anomaly_count,
        "anomaly_details": f"{anomaly_count} low-output periods detected" if anomaly_count else "none",
        "co2_kg": round(co2_kg, 1),
    }
