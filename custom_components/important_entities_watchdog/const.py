"""Constants for the Important Entities Watchdog integration."""

from __future__ import annotations

DOMAIN = "important_entities_watchdog"

CONF_LABEL = "label"
CONF_PERIOD = "period"
CONF_REALTIME = "realtime"

# The silent threshold is a freely configurable duration, stored as seconds.
DEFAULT_PERIOD_SECONDS = 86400  # 24h
# Floor: the periodic tick is period / 10, so a tiny period would poll very
# aggressively. 60s keeps the fastest tick at ~6s.
MIN_PERIOD_SECONDS = 60

DEFAULT_REALTIME = False

# Recheck interval used in real-time mode. In non-real-time mode the tick is
# derived from the period (period / 10) — see WatchdogCoordinator.
RECHECK_INTERVAL_SECONDS = 60
