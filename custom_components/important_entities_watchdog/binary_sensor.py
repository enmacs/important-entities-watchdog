"""Per-entity availability binary sensors."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util, slugify

from .const import DOMAIN
from .coordinator import WatchdogCoordinator
from .silence import is_silent

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for all currently labeled entities, and react to changes."""
    coordinator: WatchdogCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: dict[str, AvailabilityBinarySensor] = {}

    @callback
    def _sync_membership() -> None:
        current = coordinator.tracked_entities

        to_add = [eid for eid in current if eid not in known]
        to_remove = [eid for eid in known if eid not in current]

        new_entities: list[AvailabilityBinarySensor] = []
        for eid in to_add:
            ent = AvailabilityBinarySensor(coordinator, eid)
            known[eid] = ent
            new_entities.append(ent)
        if new_entities:
            async_add_entities(new_entities)

        for eid in to_remove:
            ent = known.pop(eid)
            hass.async_create_task(ent.async_remove(force_remove=True))

    @callback
    def _push_update(entity_id: str | None) -> None:
        # entity_id=None means the periodic tick: refresh every sensor so
        # that silent sources flip to "stale" once the period elapses.
        # A specific entity_id means only that source reported — updating
        # the others would be wasted work, which matters for high-frequency
        # sources.
        if entity_id is None:
            for ent in known.values():
                if ent.hass is not None:
                    ent.async_write_ha_state()
            return
        ent = known.get(entity_id)
        if ent is not None and ent.hass is not None:
            ent.async_write_ha_state()

    coordinator.register_membership_callback(_sync_membership)
    coordinator.register_update_callback(_push_update)

    # Initial population
    _sync_membership()


class AvailabilityBinarySensor(BinarySensorEntity):
    """Binary sensor: ON if the source entity reported within the period."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: WatchdogCoordinator,
        source_entity_id: str,
    ) -> None:
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._source = source_entity_id
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{source_entity_id}"
        # Friendly name kept readable. Entity_id is controlled separately via
        # suggested_object_id so it's stable and predictable regardless of name.
        self._attr_name = f"{coordinator.label_name}: {source_entity_id} ({coordinator.period_key})"
        self._attr_suggested_object_id = (
            f"{DOMAIN}_{slugify(coordinator.label_id)}_{slugify(source_entity_id)}_{coordinator.period_key}"
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the source is healthy, False if it has gone silent.

        Silence is auto-detected per source — stale reports for push sensors,
        unreachable/unavailable for connectivity sensors — see silence.py.
        """
        state = self.hass.states.get(self._source)
        return not is_silent(state, dt_util.utcnow(), self._coordinator.period_seconds)

    @property
    def extra_state_attributes(self) -> dict:
        """Expose useful detail for templates and dashboards."""
        state = self.hass.states.get(self._source)
        last_reported = None
        last_updated = None
        if state is not None:
            last_reported = state.last_reported
            last_updated = state.last_updated
        return {
            "source_entity": self._source,
            "last_reported": last_reported,
            "last_updated": last_updated,
            "period": self._coordinator.period_key,
            "period_seconds": self._coordinator.period_seconds,
        }
