"""Button entities for the Important Entities Watchdog integration."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import WatchdogCoordinator
from .dashboard import async_create_or_update_dashboard

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the maintenance buttons for this config entry."""
    coordinator: WatchdogCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CleanOrphansButton(coordinator), CreateDashboardButton(coordinator)])


class CleanOrphansButton(ButtonEntity):
    """Remove binary_sensor registry entries whose source is no longer labeled.

    A registry entry is considered an orphan when its source entity either no
    longer exists in the entity registry, or no longer carries this config
    entry's label. Currently-valid sensors are left untouched so their
    history, friendly name, and area assignment are preserved.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:broom"

    def __init__(self, coordinator: WatchdogCoordinator) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_clean_orphans"
        self._attr_name = f"Watchdog clean orphans: {coordinator.label_id} ({coordinator.period_key})"
        self._attr_suggested_object_id = (
            f"{DOMAIN}_clean_orphans_{slugify(coordinator.label_id)}_{coordinator.period_key}"
        )

    async def async_press(self) -> None:
        """Remove orphan binary_sensor entries owned by this config entry."""
        ent_reg = er.async_get(self.hass)
        entry_id = self._coordinator.entry.entry_id
        label_id = self._coordinator.label_id
        # binary_sensor unique_ids are "<entry_id>_<source_entity_id>".
        # Decoding the source back lets us check whether the source still
        # exists in the registry and still carries our label.
        prefix = f"{entry_id}_"

        removed: list[str] = []
        for registry_entry in list(ent_reg.entities.values()):
            if (
                registry_entry.config_entry_id != entry_id
                or registry_entry.domain != "binary_sensor"
                or not registry_entry.unique_id.startswith(prefix)
            ):
                continue
            source_eid = registry_entry.unique_id[len(prefix) :]
            source_reg = ent_reg.async_get(source_eid)
            if source_reg is None or label_id not in (source_reg.labels or set()):
                ent_reg.async_remove(registry_entry.entity_id)
                removed.append(registry_entry.entity_id)

        _LOGGER.info(
            "Watchdog cleaned %d orphan binary_sensor entries for label=%s: %s",
            len(removed),
            label_id,
            removed,
        )


class CreateDashboardButton(ButtonEntity):
    """Create or refresh the Watchdog Lovelace dashboard."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:view-dashboard-edit"

    def __init__(self, coordinator: WatchdogCoordinator) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_create_dashboard"
        self._attr_name = f"Watchdog create dashboard: {coordinator.label_id} ({coordinator.period_key})"
        self._attr_suggested_object_id = (
            f"{DOMAIN}_create_dashboard_{slugify(coordinator.label_id)}_{coordinator.period_key}"
        )

    async def async_press(self) -> None:
        """Create or update the Watchdog Lovelace dashboard."""
        await async_create_or_update_dashboard(self.hass)
