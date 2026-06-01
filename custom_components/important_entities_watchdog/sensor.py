"""Summary sensor exposing the number of silent entities and their IDs."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util, slugify

from .const import DOMAIN
from .coordinator import WatchdogCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the summary sensor."""
    coordinator: WatchdogCoordinator = hass.data[DOMAIN][entry.entry_id]
    sensor = SilentCountSensor(coordinator)

    coordinator.register_update_callback(
        lambda _entity_id: sensor.async_write_ha_state() if sensor.hass is not None else None
    )
    coordinator.register_membership_callback(lambda: sensor.async_write_ha_state() if sensor.hass is not None else None)

    async_add_entities([sensor])


class SilentCountSensor(SensorEntity):
    """How many tracked entities are silent right now."""

    _attr_should_poll = False
    _attr_native_unit_of_measurement = "entities"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:radar"

    def __init__(self, coordinator: WatchdogCoordinator) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_silent_count"
        self._attr_name = f"Watchdog silent entities: {coordinator.label_id} ({coordinator.period_key})"
        self._attr_suggested_object_id = f"{DOMAIN}_silent_{slugify(coordinator.label_id)}_{coordinator.period_key}"

    def _compute_silent(self) -> list[str]:
        """Return entity_ids whose source has not reported within the period."""
        now = dt_util.utcnow()
        threshold = self._coordinator.period_seconds
        silent: list[str] = []
        for eid in self._coordinator.tracked_entities:
            state = self.hass.states.get(eid)
            if state is None:
                silent.append(eid)
                continue
            last = state.last_reported or state.last_updated
            if last is None:
                silent.append(eid)
                continue
            if (now - last).total_seconds() >= threshold:
                silent.append(eid)
        return silent

    @property
    def native_value(self) -> int:
        """Return the count of silent entities."""
        return len(self._compute_silent())

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the lists of silent and tracked entities for templating."""
        silent = self._compute_silent()
        tracked = sorted(self._coordinator.tracked_entities)
        return {
            "silent_entities": silent,
            "tracked_entities": tracked,
            "tracked_count": len(tracked),
            "period": self._coordinator.period_key,
            "period_seconds": self._coordinator.period_seconds,
            "label_id": self._coordinator.label_id,
        }
