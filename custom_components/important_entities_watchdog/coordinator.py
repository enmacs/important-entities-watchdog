"""Coordinator that tracks labeled entities and triggers sensor recomputation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_state_report_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import CONF_LABEL, CONF_PERIOD, CONF_REALTIME, DEFAULT_REALTIME, PERIOD_OPTIONS, RECHECK_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

# Event names. These are stable across recent HA versions but if a future
# version renames them, update here.
EVENT_ENTITY_REGISTRY_UPDATED = "entity_registry_updated"
EVENT_LABEL_REGISTRY_UPDATED = "label_registry_updated"


class WatchdogCoordinator:
    """Tracks which entities carry the configured label.

    Notifies registered callbacks when membership changes or on a periodic
    tick so that downstream sensors can recompute their state.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.label_id: str = entry.data[CONF_LABEL]

        # Options override entry data so settings can be changed without
        # recreating the entry.
        period_key = entry.options.get(CONF_PERIOD, entry.data[CONF_PERIOD])
        self.period_key: str = period_key
        self.period_seconds: int = PERIOD_OPTIONS[period_key]

        # Real-time mode: subscribe to source state events for immediate
        # re-evaluation. When disabled, we only tick periodically — much
        # cheaper for high-frequency sources and long periods.
        self.realtime: bool = entry.options.get(CONF_REALTIME, entry.data.get(CONF_REALTIME, DEFAULT_REALTIME))
        # Tick interval: fixed 60s in real-time mode (the events do the
        # heavy lifting, the tick only catches "going silent"); otherwise
        # period/10 — fine-grained enough to detect staleness within 10%
        # of the configured period.
        self.tick_seconds: int = RECHECK_INTERVAL_SECONDS if self.realtime else max(1, self.period_seconds // 10)

        self._unsubs: list[Callable[[], None]] = []
        self._source_unsubs: list[Callable[[], None]] = []
        self._tracked_entities: set[str] = set()

        # When the next periodic tick is expected to fire. Updated on each
        # tick and once at init so the summary sensor can expose it as an
        # attribute. Approximate — driven from "now + tick_seconds" rather
        # than HA's internal scheduler state.
        self.next_tick_at: datetime | None = None

        # Instance-scoped callback lists. Do NOT make these class attributes
        # — they would leak across config entries.
        # Update callback receives the entity_id of the source that fired,
        # or None on the periodic tick (meaning "refresh everything").
        self._update_callbacks: list[Callable[[str | None], None]] = []
        self._membership_callbacks: list[Callable[[], None]] = []

    async def async_init(self) -> None:
        """Initialize the coordinator and start listening."""
        self._refresh_tracked_entities()
        self._sync_source_subscriptions()

        self._unsubs.append(self.hass.bus.async_listen(EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_change))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_LABEL_REGISTRY_UPDATED, self._handle_registry_change))
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._handle_tick,
                timedelta(seconds=self.tick_seconds),
            )
        )
        self.next_tick_at = dt_util.utcnow() + timedelta(seconds=self.tick_seconds)

        _LOGGER.debug(
            "Watchdog initialized for label=%s period=%s realtime=%s tick=%ds tracking %d entities",
            self.label_id,
            self.period_key,
            self.realtime,
            self.tick_seconds,
            len(self._tracked_entities),
        )

    async def async_shutdown(self) -> None:
        """Stop listening."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for unsub in self._source_unsubs:
            unsub()
        self._source_unsubs.clear()
        self._update_callbacks.clear()
        self._membership_callbacks.clear()

    @callback
    def _refresh_tracked_entities(self) -> None:
        """Recompute the set of tracked entities from the registry."""
        ent_reg = er.async_get(self.hass)
        self._tracked_entities = {
            ent.entity_id for ent in ent_reg.entities.values() if self.label_id in (ent.labels or set())
        }

    @callback
    def _handle_registry_change(self, event: Event) -> None:
        """Refresh membership when entity or label registries change."""
        old = self._tracked_entities.copy()
        self._refresh_tracked_entities()
        if old != self._tracked_entities:
            _LOGGER.debug(
                "Membership for label=%s changed: +%s -%s",
                self.label_id,
                self._tracked_entities - old,
                old - self._tracked_entities,
            )
            self._sync_source_subscriptions()
            for cb in list(self._membership_callbacks):
                cb()

    @callback
    def _sync_source_subscriptions(self) -> None:
        """(Re)subscribe to state-change and state-report events for tracked sources.

        Skipped entirely when real-time mode is off — staleness is then
        evaluated only on the periodic tick, which is the whole point of
        the low-load mode.
        """
        for unsub in self._source_unsubs:
            unsub()
        self._source_unsubs.clear()

        if not self.realtime or not self._tracked_entities:
            return

        entities = list(self._tracked_entities)
        # state_changed fires only when state/attrs change; state_reported
        # fires when a source re-reports the same value. Both bump
        # state.last_reported, so we listen to both.
        self._source_unsubs.append(async_track_state_change_event(self.hass, entities, self._handle_source_event))
        self._source_unsubs.append(async_track_state_report_event(self.hass, entities, self._handle_source_event))

    @callback
    def _handle_source_event(self, event) -> None:
        """A tracked source reported or changed — notify with its entity_id.

        Untyped event because this handler is registered with both
        async_track_state_change_event (Event[EventStateChangedData]) and
        async_track_state_report_event (Event[EventStateReportedData]),
        and Event's generic is invariant. Both payloads carry "entity_id".
        """
        entity_id: str | None = event.data.get("entity_id")
        for cb in list(self._update_callbacks):
            cb(entity_id)

    @callback
    def _handle_tick(self, now: datetime) -> None:
        """Periodic recompute — None signals "refresh all tracked entities"."""
        self.next_tick_at = now + timedelta(seconds=self.tick_seconds)
        for cb in list(self._update_callbacks):
            cb(None)

    @callback
    def register_update_callback(self, cb: Callable[[str | None], None]) -> Callable[[], None]:
        """Register a callback for source updates.

        The callback receives the entity_id of the source that fired, or
        None on the periodic tick (refresh everything). Returns an
        unsubscribe fn.
        """
        self._update_callbacks.append(cb)

        def _unregister() -> None:
            if cb in self._update_callbacks:
                self._update_callbacks.remove(cb)

        return _unregister

    @callback
    def register_membership_callback(self, cb: Callable[[], None]) -> Callable[[], None]:
        """Register a callback invoked when label membership changes."""
        self._membership_callbacks.append(cb)

        def _unregister() -> None:
            if cb in self._membership_callbacks:
                self._membership_callbacks.remove(cb)

        return _unregister

    @property
    def tracked_entities(self) -> set[str]:
        """Return the current set of entity IDs carrying the configured label."""
        return self._tracked_entities
