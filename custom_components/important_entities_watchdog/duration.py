"""Helpers for the freely-configurable silent-threshold duration.

The threshold is stored as an integer number of seconds. These helpers derive
the two string forms the rest of the integration needs:

- ``format_period`` — a compact, slug-safe canonical string (e.g. 5400 ->
  "1h30m") used for entity_ids, unique_ids, dashboard paths/titles and the
  ``period`` attribute. Deterministic from the seconds value, so the same
  duration always yields the same string (no id/uniqueness drift).
- ``seconds_to_duration_dict`` — split seconds into the {days, hours, minutes,
  seconds} mapping the HA DurationSelector expects, for pre-filling the form.
"""

from __future__ import annotations

_UNITS: tuple[tuple[str, int], ...] = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))


def format_period(seconds: int) -> str:
    """Return a compact canonical slug for a duration in seconds (e.g. "1h30m")."""
    remaining = int(seconds)
    if remaining <= 0:
        return "0s"
    parts: list[str] = []
    for suffix, size in _UNITS:
        if remaining >= size:
            qty, remaining = divmod(remaining, size)
            parts.append(f"{qty}{suffix}")
    return "".join(parts)


def seconds_to_duration_dict(seconds: int) -> dict[str, int]:
    """Split seconds into a DurationSelector mapping."""
    remaining = int(seconds)
    days, remaining = divmod(remaining, 86400)
    hours, remaining = divmod(remaining, 3600)
    minutes, remaining = divmod(remaining, 60)
    return {"days": days, "hours": hours, "minutes": minutes, "seconds": remaining}
