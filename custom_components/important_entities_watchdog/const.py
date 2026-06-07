"""Constants for the Important Entities Watchdog integration."""

from __future__ import annotations

DOMAIN = "important_entities_watchdog"

CONF_LABEL = "label"
CONF_PERIOD = "period"
CONF_REALTIME = "realtime"

# Period choices shown in the UI -> seconds
PERIOD_OPTIONS: dict[str, int] = {
    "1m": 60,
    "10m": 600,
    "1h": 3600,
    "6h": 21600,
    "12h": 43200,
    "24h": 86400,
    "7d": 604800,
}

DEFAULT_PERIOD = "24h"
DEFAULT_REALTIME = False

# Recheck interval used in real-time mode. In non-real-time mode the tick is
# derived from the period (period / 10) — see WatchdogCoordinator.
RECHECK_INTERVAL_SECONDS = 60
