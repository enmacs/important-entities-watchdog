"""Constants for the Important Entities Watchdog integration."""

from __future__ import annotations

DOMAIN = "important_entities_watchdog"

CONF_LABEL = "label"
CONF_PERIOD = "period"

# Period choices shown in the UI -> seconds
PERIOD_OPTIONS: dict[str, int] = {
    "10m": 600,
    "1h": 3600,
    "6h": 21600,
    "12h": 43200,
    "24h": 86400,
    "7d": 604800,
}

DEFAULT_PERIOD = "24h"

# How often the coordinator re-evaluates staleness even when no source updates occur.
# Needed because "going stale" is the absence of events; nothing fires when a device
# crosses the threshold by simply not reporting.
RECHECK_INTERVAL_SECONDS = 60
