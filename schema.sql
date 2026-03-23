-- ============================================================
-- SuperCharge SG Dashboard — Supabase Schema
-- Run this entire file in your Supabase SQL Editor
-- ============================================================

-- Organisations (tenants)
CREATE TABLE IF NOT EXISTS organisations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Users per org
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Sites per org
CREATE TABLE IF NOT EXISTS sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    lat FLOAT DEFAULT 1.3521,
    lng FLOAT DEFAULT 103.8198,
    solar_kwp FLOAT DEFAULT 5.0,
    charger_count INT DEFAULT 2,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Solar readings (time-series)
CREATE TABLE IF NOT EXISTS solar_readings (
    id BIGSERIAL PRIMARY KEY,
    site_id UUID REFERENCES sites(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ DEFAULT now(),
    power_kw FLOAT,
    energy_kwh FLOAT,
    irradiance FLOAT,
    temp_c FLOAT,
    expected_kw FLOAT,
    performance_ratio FLOAT,
    anomaly_flag BOOLEAN DEFAULT FALSE,
    anomaly_severity TEXT DEFAULT 'OK'
);

-- EV charging sessions
CREATE TABLE IF NOT EXISTS ev_sessions (
    id BIGSERIAL PRIMARY KEY,
    site_id UUID REFERENCES sites(id) ON DELETE CASCADE,
    charger_id TEXT,
    start_ts TIMESTAMPTZ DEFAULT now(),
    end_ts TIMESTAMPTZ,
    energy_kwh FLOAT DEFAULT 0,
    revenue_sgd FLOAT DEFAULT 0,
    status TEXT DEFAULT 'Available'
);

-- Index for fast time-series queries
CREATE INDEX IF NOT EXISTS idx_solar_site_ts ON solar_readings(site_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ev_site_ts ON ev_sessions(site_id, start_ts DESC);

-- ============================================================
-- Seed data — two orgs, two users, three sites
-- Passwords below are bcrypt hashes of:
--   clientA@test.com → passwordA
--   clientB@test.com → passwordB
-- The app will re-hash on first run if you use the /seed endpoint
-- ============================================================

INSERT INTO organisations (id, name) VALUES
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Client A — Sunshine Condo'),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'Client B — GreenPark Mall')
ON CONFLICT DO NOTHING;

INSERT INTO sites (id, org_id, name, solar_kwp, charger_count) VALUES
    ('11111111-1111-1111-1111-111111111111', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Sunshine Condo Block A', 8.0, 4),
    ('22222222-2222-2222-2222-222222222222', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Sunshine Condo Block B', 5.5, 2),
    ('33333333-3333-3333-3333-333333333333', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'GreenPark Mall Rooftop', 30.0, 8)
ON CONFLICT DO NOTHING;