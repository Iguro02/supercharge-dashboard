"""
anomaly.py — Isolation Forest anomaly detection.
Flags when actual solar output deviates >20% below expected.
Contamination set low (0.02) to avoid false positives on fresh data.
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
    """Train Isolation Forest on historical reading dicts."""
    global _model
    if len(historical_readings) < 20:
        print("[Anomaly] Not enough data to train model yet.")
        return

    X = np.vstack([_build_features(r) for r in historical_readings])
    # contamination=0.02 means only flag the most extreme 2% as anomalies
    model = IsolationForest(contamination=0.02, random_state=42, n_estimators=100)
    model.fit(X)

    with _lock:
        _model = model
    print(f"[Anomaly] Model trained on {len(historical_readings)} readings.")


def score_reading(reading: dict) -> dict:
    """
    Score a single reading.
    Rule-based threshold: >20% drop flags WARNING, >35% drop flags CRITICAL.
    ML model only fires on top of rule-based check — not independently.
    Returns: {"anomaly": bool, "severity": "OK"|"WARNING"|"CRITICAL", "score": float}
    """
    with _lock:
        model = _model

    expected = reading.get("expected_kw", 1.0) or 1.0
    actual = reading.get("power_kw", 0.0)
    irradiance = reading.get("irradiance", 0.0)

    # Skip if irradiance too low
    if irradiance < 0.1:
        return {"anomaly": False, "severity": "OK", "score": 0.0}

    # Calculate drop percentage
    drop_pct = (1 - actual / expected) if expected > 0 else 0.0

    # Rule-based: only flag if drop is meaningful (>20%)
    # This prevents 1-2% natural variation from being flagged
    if drop_pct > 0.35:
        return {"anomaly": True, "severity": "CRITICAL", "score": round(-drop_pct, 4)}

    if drop_pct > 0.20:
        return {"anomaly": True, "severity": "WARNING", "score": round(-drop_pct, 4)}

    # ML model as secondary check — only flag if BOTH model AND drop > 15%
    if model is not None and drop_pct > 0.15:
        X = _build_features(reading)
        score = float(model.decision_function(X)[0])
        is_anomaly = model.predict(X)[0] == -1
        if is_anomaly:
            severity = "CRITICAL" if score < -0.3 else "WARNING"
            return {"anomaly": True, "severity": severity, "score": round(score, 4)}

    return {"anomaly": False, "severity": "OK", "score": 0.0}


def retrain_from_db(site_id: str = None):
    """Pull recent readings from DB and retrain model."""
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
