"""Service action handlers for Important Entities Watchdog."""

from __future__ import annotations

from custom_components.important_entities_watchdog.const import DOMAIN
from custom_components.important_entities_watchdog.dashboard import async_create_or_update_dashboard
from homeassistant.core import HomeAssistant, ServiceCall


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register domain-level service actions."""
    if hass.services.has_service(DOMAIN, "create_dashboard"):
        return

    async def handle_create_dashboard(_call: ServiceCall) -> None:
        await async_create_or_update_dashboard(hass)

    hass.services.async_register(DOMAIN, "create_dashboard", handle_create_dashboard)
