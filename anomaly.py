"""
anomaly.py — Isolation Forest anomaly detection.
Trained on historical readings. Scores each new reading in real-time.
Flags when actual solar output deviates >15% below expected.
"""
import numpy as np
from sklearn.ensemble import IsolationForest
import threading

_model: IsolationForest = None
_lock = threading.Lock()


def _build_features(reading: dict) -> np.ndarray:
    """Extract feature vector from a solar reading."""
    expected = reading.get("expected_kw", 1.0) or 1.0
    actual = reading.get("power_kw", 0.0)
    perf_ratio = reading.get("performance_ratio", 1.0)
    temp_c = reading.get("temp_c", 32.0)
    irradiance = reading.get("irradiance", 3.0)
    actual_vs_expected = (actual / expected) if expected > 0 else 1.0

    return np.array([[perf_ratio, actual_vs_expected, temp_c, irradiance]])


def train_model(historical_readings: list[dict]):
    """Train Isolation Forest on a list of historical reading dicts."""
    global _model
    if len(historical_readings) < 10:
        print("[Anomaly] Not enough data to train model yet.")
        return

    X = np.vstack([_build_features(r) for r in historical_readings])
    model = IsolationForest(contamination=0.05, random_state=42, n_estimators=100)
    model.fit(X)

    with _lock:
        _model = model
    print(f"[Anomaly] Model trained on {len(historical_readings)} readings.")


def score_reading(reading: dict) -> dict:
    """
    Score a single reading.
    Returns: {"anomaly": bool, "severity": "OK"|"WARNING"|"CRITICAL", "score": float}
    """
    with _lock:
        model = _model

    expected = reading.get("expected_kw", 1.0) or 1.0
    actual = reading.get("power_kw", 0.0)
    irradiance = reading.get("irradiance", 0.0)

    # Rule-based pre-check: if irradiance is near zero, no anomaly expected
    if irradiance < 0.3:
        return {"anomaly": False, "severity": "OK", "score": 0.0}

    # Rule-based check: >15% below expected → always flag
    if expected > 0 and (actual / expected) < 0.85:
        drop_pct = 1 - (actual / expected)
        severity = "CRITICAL" if drop_pct > 0.35 else "WARNING"
        return {"anomaly": True, "severity": severity, "score": -drop_pct}

    # ML model scoring (if trained)
    if model is not None:
        X = _build_features(reading)
        score = float(model.decision_function(X)[0])
        is_anomaly = model.predict(X)[0] == -1
        if is_anomaly:
            severity = "CRITICAL" if score < -0.3 else "WARNING"
        else:
            severity = "OK"
        return {"anomaly": is_anomaly, "severity": severity, "score": round(score, 4)}

    return {"anomaly": False, "severity": "OK", "score": 0.0}


def retrain_from_db(site_id: str = None):
    """
    Pull recent readings from DB and retrain model.
    Called periodically by APScheduler.
    """
    import database as db

    try:
        res = db.get_db().table("solar_readings").select(
            "power_kw, expected_kw, performance_ratio, temp_c, irradiance"
        ).order("ts", desc=True).limit(500).execute()

        readings = res.data
        if readings:
            train_model(readings)
    except Exception as e:
        print(f"[Anomaly] Retrain failed: {e}")
