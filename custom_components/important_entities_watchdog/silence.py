"""Unified "is this source silent?" rule shared by the sensor platforms.

A source is *silent* when it has been in a bad condition for at least the
watchdog period. What counts as "bad" is auto-detected per entity, so a single
period means the same thing — "how long may this important thing be gone before
I'm told" — regardless of how the source signals trouble:

- missing state / ``unavailable`` / ``unknown`` -> gone; bad since ``last_changed``
- ``connectivity`` device_class reading ``off`` -> unreachable; bad since
  ``last_changed`` (judged purely by reachability, never by report age, because
  a ping sensor keeps reporting a fresh ``last_reported`` even while down)
- everything else -> classic staleness; bad measured as the age of
  ``last_reported`` (the last moment the push source proved it was alive)

This keeps one user-facing concept ("don't let important things vanish") while
still catching IP/ping devices that report a current timestamp but are offline.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS, STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State


def unhealthy_seconds(state: State | None, now: datetime) -> float:
    """Return how long the source has been in a bad condition, in seconds.

    ``0.0`` means healthy right now. ``float("inf")`` means bad with no usable
    onset timestamp (treated as silent regardless of the period).
    """
    if state is None:
        return float("inf")

    value = state.state
    if value in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return (now - state.last_changed).total_seconds()

    if state.attributes.get(ATTR_DEVICE_CLASS) == BinarySensorDeviceClass.CONNECTIVITY:
        # Reachability sensors keep reporting while down, so report-age is
        # meaningless here — judge purely by the on/off value.
        if value == STATE_OFF:
            return (now - state.last_changed).total_seconds()
        return 0.0

    # Push sources are healthy each time they report, so the time since the
    # last report is exactly how long they have been silent.
    last = state.last_reported or state.last_updated
    if last is None:
        return float("inf")
    return (now - last).total_seconds()


def is_silent(state: State | None, now: datetime, period_seconds: float) -> bool:
    """Return True if the source has been bad for at least ``period_seconds``."""
    return unhealthy_seconds(state, now) >= period_seconds
