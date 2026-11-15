"""Pure, testable source selection. Temperatures are normalized to Celsius."""

import math


def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def timestamp(value):
    v = number(value)
    if v is not None and v > 1e12:
        v /= 1000
    return v


def choose(candidates, now, max_age=180):
    valid = []
    for c in candidates:
        t = timestamp(c.get("timestamp"))
        v = number(c.get("value"))
        if t is None or v is None or t > now + 10 or now - t > max_age:
            continue
        unit = c.get("unit")
        if unit in ("°F", "F"):
            v = (v - 32) * 5 / 9
        elif unit not in ("°C", "C"):
            continue
        if v < -50 or v > 550:
            continue
        valid.append({**c, "value": v, "timestamp": t, "unit": "°C"})
    # Prefer local BLE only when timestamps are exactly tied.
    return max(valid, key=lambda c: (c["timestamp"], c["source"] == "bluetooth"), default=None)
