"""Important Entities Watchdog integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import WatchdogCoordinator
from .entity_ids import (
    binary_sensor_entity_id,
    clean_orphans_entity_id,
    create_dashboard_entity_id,
    summary_sensor_entity_id,
)
from .service_actions import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["binary_sensor", "button", "sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@callback
def _migrate_entity_ids(hass: HomeAssistant, entry: ConfigEntry, coordinator: WatchdogCoordinator) -> None:
    """Rename pre-existing entities to the deterministic entity_id scheme.

    Earlier versions relied on ``_attr_suggested_object_id``, which HA ignores —
    so registered entity_ids were derived from the (display) name instead. Now
    that entities pin ``self.entity_id`` explicitly, migrate any already-created
    registry entries so they line up with the documented, stable ids.
    """
    ent_reg = er.async_get(hass)
    entry_prefix = f"{entry.entry_id}_"
    label_id = coordinator.label_id
    period = coordinator.period_key

    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        uid = reg_entry.unique_id
        if reg_entry.domain == "binary_sensor" and uid.startswith(entry_prefix):
            desired = binary_sensor_entity_id(label_id, uid[len(entry_prefix) :], period)
        elif reg_entry.domain == "sensor" and uid.endswith("_silent_count"):
            desired = summary_sensor_entity_id(label_id, period)
        elif reg_entry.domain == "button" and uid.endswith("_clean_orphans"):
            desired = clean_orphans_entity_id(label_id, period)
        elif reg_entry.domain == "button" and uid.endswith("_create_dashboard"):
            desired = create_dashboard_entity_id(label_id, period)
        else:
            continue

        if reg_entry.entity_id == desired:
            continue
        if ent_reg.async_get(desired) is not None:
            _LOGGER.warning(
                "Skipping entity_id migration %s -> %s: target already exists",
                reg_entry.entity_id,
                desired,
            )
            continue
        _LOGGER.info("Migrating watchdog entity_id %s -> %s", reg_entry.entity_id, desired)
        ent_reg.async_update_entity(reg_entry.entity_id, new_entity_id=desired)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up domain-level services."""
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    coordinator = WatchdogCoordinator(hass, entry)
    await coordinator.async_init()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Align any pre-existing entities with the deterministic entity_id scheme
    # before the platforms (re)create them.
    _migrate_entity_ids(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload entry when options change (period or real-time mode)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: WatchdogCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
