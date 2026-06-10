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
    """Remove orphan binary_sensor registry entries across all watchdogs.

    A registry entry is considered an orphan when its source entity either no
    longer exists in the entity registry, or no longer carries the label
    belonging to its owning config entry. Currently-valid sensors are left
    untouched so their history, friendly name, and area assignment are
    preserved.

    Pressing this rebuilds nothing — it just cleans up. The action spans
    every configured watchdog, not only the entry this button belongs to.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:broom"

    def __init__(self, coordinator: WatchdogCoordinator) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_clean_orphans"
        self._attr_name = f"Clean orphans: {coordinator.label_name} ({coordinator.period_key})"
        self._attr_suggested_object_id = (
            f"{DOMAIN}_clean_orphans_{slugify(coordinator.label_id)}_{coordinator.period_key}"
        )

    async def async_press(self) -> None:
        """Remove orphan binary_sensor entries across every watchdog entry."""
        ent_reg = er.async_get(self.hass)
        domain_data = self.hass.data.get(DOMAIN, {})
        total_removed: list[str] = []

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            coordinator: WatchdogCoordinator | None = domain_data.get(entry.entry_id)
            if coordinator is None:
                continue

            entry_id = entry.entry_id
            label_id = coordinator.label_id
            # binary_sensor unique_ids are "<entry_id>_<source_entity_id>".
            # Decoding the source back lets us check whether the source still
            # exists in the registry and still carries the owning label.
            prefix = f"{entry_id}_"

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
                    total_removed.append(registry_entry.entity_id)

        _LOGGER.info(
            "Watchdog cleaned %d orphan binary_sensor entries across all watchdogs: %s",
            len(total_removed),
            total_removed,
        )


class CreateDashboardButton(ButtonEntity):
    """Create or refresh the Watchdog Lovelace dashboards.

    Pressing this rebuilds the entire `entity-watchdog` Lovelace dashboard,
    including the overview and a view per configured (label, period) entry —
    not just the entry this button belongs to.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:view-dashboard-edit"

    def __init__(self, coordinator: WatchdogCoordinator) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_create_dashboard"
        self._attr_name = f"Create dashboards: {coordinator.label_name} ({coordinator.period_key})"
        self._attr_suggested_object_id = (
            f"{DOMAIN}_create_dashboard_{slugify(coordinator.label_id)}_{coordinator.period_key}"
        )

    async def async_press(self) -> None:
        """Create or update the Watchdog Lovelace dashboard."""
        await async_create_or_update_dashboard(self.hass)
