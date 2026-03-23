"""
database.py — Supabase client and all DB query functions.
All queries are scoped by org_id for multi-tenant isolation.
"""
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_client: Client = None

def get_db() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
    return _client


# ── Users ──────────────────────────────────────────────────────────────────

def get_user_by_email(email: str):
    db = get_db()
    res = db.table("users").select("*").eq("email", email).execute()
    return res.data[0] if res.data else None


def create_user(org_id: str, email: str, hashed_password: str):
    db = get_db()
    res = db.table("users").insert({
        "org_id": org_id,
        "email": email,
        "hashed_password": hashed_password
    }).execute()
    return res.data[0] if res.data else None


# ── Sites ──────────────────────────────────────────────────────────────────

def get_sites_for_org(org_id: str):
    db = get_db()
    res = db.table("sites").select("*").eq("org_id", org_id).execute()
    return res.data


def get_site(site_id: str, org_id: str):
    """Returns site only if it belongs to the org — enforces isolation."""
    db = get_db()
    res = db.table("sites").select("*").eq("id", site_id).eq("org_id", org_id).execute()
    return res.data[0] if res.data else None


# ── Solar readings ─────────────────────────────────────────────────────────

def insert_solar_reading(reading: dict):
    db = get_db()
    db.table("solar_readings").insert(reading).execute()


def get_latest_solar(site_id: str, limit: int = 48):
    """Last N readings for a site (for chart)."""
    db = get_db()
    res = (db.table("solar_readings")
           .select("*")
           .eq("site_id", site_id)
           .order("ts", desc=True)
           .limit(limit)
           .execute())
    return list(reversed(res.data))


def get_solar_summary(site_id: str, days: int = 7):
    """Aggregate stats for weekly digest / PDF."""
    db = get_db()
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    res = (db.table("solar_readings")
           .select("energy_kwh, anomaly_flag, anomaly_severity, ts")
           .eq("site_id", site_id)
           .gte("ts", since)
           .execute())
    return res.data


def get_anomalies(site_id: str, limit: int = 20):
    db = get_db()
    res = (db.table("solar_readings")
           .select("*")
           .eq("site_id", site_id)
           .eq("anomaly_flag", True)
           .order("ts", desc=True)
           .limit(limit)
           .execute())
    return res.data


# ── EV sessions ────────────────────────────────────────────────────────────

def insert_ev_session(session: dict):
    db = get_db()
    db.table("ev_sessions").insert(session).execute()


def get_ev_sessions(site_id: str, limit: int = 20):
    db = get_db()
    res = (db.table("ev_sessions")
           .select("*")
           .eq("site_id", site_id)
           .order("start_ts", desc=True)
           .limit(limit)
           .execute())
    return res.data


def get_ev_summary(site_id: str, days: int = 7):
    db = get_db()
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    res = (db.table("ev_sessions")
           .select("energy_kwh, revenue_sgd, status")
           .eq("site_id", site_id)
           .gte("start_ts", since)
           .execute())
    return res.data
