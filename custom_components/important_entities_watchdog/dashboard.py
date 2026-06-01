"""Lovelace dashboard creation for Important Entities Watchdog."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.components.lovelace.const import (
    CONF_REQUIRE_ADMIN,
    CONF_SHOW_IN_SIDEBAR,
    CONF_TITLE,
    CONF_URL_PATH,
    LOVELACE_DATA,
    MODE_STORAGE,
)
from homeassistant.components.lovelace.dashboard import DashboardsCollection, LovelaceStorage
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL_PATH = "entity-watchdog"
DASHBOARD_TITLE = "Entity Watchdog"
DASHBOARD_ICON = "mdi:radar"


_SILENT_NOW_TEMPLATE = """\
{% set summary = '__SUMMARY__' %}
{% set silent = state_attr(summary, 'silent_entities') or [] %}
{% if silent %}
**{{ silent | count }} silent**

| Entity | Last reported | Device |
|---|---|---|
{% for eid in silent -%}
  {%- set did = device_id(eid) -%}
| `{{ eid }}` | {% if states[eid] and states[eid].last_reported %}{{ relative_time(states[eid].last_reported) }} ago{% else %}—{% endif %} | {% if did %}[Gerät](/config/devices/device/{{ did }}){% else %}—{% endif %} |
{% endfor %}
{% else %}
All tracked entities reporting within period.
{% endif %}
"""

_ALL_TRACKED_TEMPLATE = """\
{% set summary = '__SUMMARY__' %}
{% set tracked = state_attr(summary, 'tracked_entities') or [] %}
{% set silent = state_attr(summary, 'silent_entities') or [] %}
{% if tracked %}
| Entity | State | Last reported | Device |
|---|---|---|---|
{% for eid in tracked | sort -%}
  {%- set did = device_id(eid) -%}
| `{{ eid }}` | {% if eid in silent %}silent{% else %}fresh{% endif %} | {% if states[eid] and states[eid].last_reported %}{{ relative_time(states[eid].last_reported) }} ago{% else %}—{% endif %} | {% if did %}[Gerät](/config/devices/device/{{ did }}){% else %}—{% endif %} |
{% endfor %}
{% else %}
No entities carry the label yet.
{% endif %}
"""


def _get_entry_key_entities(hass: HomeAssistant, entry: ConfigEntry) -> tuple[str | None, str | None]:
    """Return (summary_sensor_id, clean_orphans_button_id) for the entry."""
    ent_reg = er.async_get(hass)
    summary: str | None = None
    clean_orphans: str | None = None
    for ent in ent_reg.entities.values():
        if ent.config_entry_id != entry.entry_id:
            continue
        if ent.domain == "sensor" and ent.entity_category is None:
            summary = ent.entity_id
        elif (
            ent.domain == "button"
            and ent.entity_category == EntityCategory.CONFIG
            and ent.unique_id.endswith("_clean_orphans")
        ):
            clean_orphans = ent.entity_id
    return summary, clean_orphans


def _build_view(label: str, period: str, summary_eid: str, clean_orphans_eid: str | None) -> dict[str, Any]:
    """Build a sections view for one (label, period) entry."""
    header_cards: list[dict[str, Any]] = [
        {
            "type": "heading",
            "icon": "mdi:fridge",
            "heading": f"{period} silent",
            "heading_style": "title",
        },
        {
            "type": "tile",
            "entity": summary_eid,
            "name": f"Silent count ({period})",
            "color": "orange",
        },
    ]
    if clean_orphans_eid:
        header_cards.append(
            {
                "type": "button",
                "entity": clean_orphans_eid,
                "name": "Clean orphans",
                "icon": "mdi:broom",
                "show_state": False,
            }
        )

    silent_now = _SILENT_NOW_TEMPLATE.replace("__SUMMARY__", summary_eid)
    all_tracked = _ALL_TRACKED_TEMPLATE.replace("__SUMMARY__", summary_eid)

    return {
        "title": f"Watchdog {label} {period}",
        "icon": "",
        "path": f"watchdog-{slugify(label)}-{period}",
        "type": "sections",
        "sections": [
            {
                "type": "grid",
                "cards": header_cards,
            },
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "markdown",
                        "title": f"{period} Silent now",
                        "content": silent_now,
                        "grid_options": {"columns": 48, "rows": "auto"},
                    }
                ],
                "column_span": 2,
            },
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "markdown",
                        "title": f"All tracked {period}",
                        "content": all_tracked,
                        "grid_options": {"columns": 48, "rows": "auto"},
                    }
                ],
                "column_span": 4,
            },
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "custom:auto-entities",
                        "card": {
                            "type": "history-graph",
                            "title": f"Tracked sources ({period})",
                            "hours_to_show": 24,
                        },
                        "filter": {"include": [{"entity_id": f"binary_sensor.{DOMAIN}_{slugify(label)}_*_{period}"}]},
                        "show_empty": False,
                        "grid_options": {"columns": 48, "rows": "auto"},
                    }
                ],
                "column_span": 4,
            },
        ],
        "max_columns": 4,
        "cards": [],
    }


def _generate_lovelace_config(hass: HomeAssistant) -> dict[str, Any]:
    """Build a Lovelace dashboard config from all active config entries."""
    entries = hass.config_entries.async_entries(DOMAIN)
    views: list[dict[str, Any]] = []

    for entry in entries:
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator is None:
            continue

        summary_eid, clean_orphans_eid = _get_entry_key_entities(hass, entry)
        if summary_eid is None:
            _LOGGER.warning("No summary sensor found for entry %s; skipping view", entry.entry_id)
            continue

        views.append(_build_view(coordinator.label_id, coordinator.period_key, summary_eid, clean_orphans_eid))

    if not views:
        views.append(
            {
                "title": "Watchdog",
                "path": "overview",
                "cards": [
                    {
                        "type": "markdown",
                        "content": "No watchdog entries configured yet. Add a configuration entry first.",
                    }
                ],
            }
        )

    return {"title": DASHBOARD_TITLE, "views": views}


def _panel_exists(hass: HomeAssistant, frontend_url_path: str) -> bool:
    # async_panel_exists was added in HA 2026.5; replicate its logic for 2026.4 compat.
    return frontend_url_path in hass.data.get("frontend_panels", {})


async def async_create_or_update_dashboard(hass: HomeAssistant) -> None:
    """Create or update the Watchdog Lovelace dashboard.

    On first call: writes the dashboard to lovelace's storage collection
    (which persists across restarts) and registers the sidebar panel in
    the current session.

    On subsequent calls: updates the dashboard config in place so the
    view list stays in sync with the current config entries.
    """
    config = _generate_lovelace_config(hass)

    if _panel_exists(hass, DASHBOARD_URL_PATH):
        lovelace_data = hass.data.get(LOVELACE_DATA)
        if lovelace_data is not None:
            existing = lovelace_data.dashboards.get(DASHBOARD_URL_PATH)
            if existing is not None:
                await existing.async_save(config)
                _LOGGER.info("Updated Watchdog dashboard at /%s", DASHBOARD_URL_PATH)
                return
        _LOGGER.warning(
            "Panel %s already registered but no matching lovelace dashboard found",
            DASHBOARD_URL_PATH,
        )
        return

    # Load the collection to check whether a prior (orphaned) entry exists in storage.
    collection = DashboardsCollection(hass)
    await collection.async_load()

    existing_item: dict[str, Any] | None = next(
        (v for v in collection.data.values() if v.get(CONF_URL_PATH) == DASHBOARD_URL_PATH),
        None,
    )

    if existing_item is None:
        try:
            existing_item = await collection.async_create_item(
                {
                    CONF_URL_PATH: DASHBOARD_URL_PATH,
                    CONF_TITLE: DASHBOARD_TITLE,
                    "icon": DASHBOARD_ICON,
                    CONF_SHOW_IN_SIDEBAR: True,
                    CONF_REQUIRE_ADMIN: False,
                    "mode": MODE_STORAGE,
                }
            )
        except HomeAssistantError as err:
            _LOGGER.error("Failed to register dashboard in lovelace collection: %s", err)
            return

    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        _LOGGER.error(
            "Lovelace not initialised; dashboard saved to storage but the sidebar "
            "panel will appear after the next Home Assistant restart."
        )
        return

    lovelace_data.dashboards[DASHBOARD_URL_PATH] = LovelaceStorage(hass, existing_item)

    async_register_built_in_panel(
        hass,
        component_name="lovelace",
        sidebar_title=DASHBOARD_TITLE,
        sidebar_icon=DASHBOARD_ICON,
        frontend_url_path=DASHBOARD_URL_PATH,
        config={"mode": MODE_STORAGE},
        require_admin=False,
        show_in_sidebar=True,
    )

    await lovelace_data.dashboards[DASHBOARD_URL_PATH].async_save(config)
    _LOGGER.info("Created Watchdog dashboard at /%s", DASHBOARD_URL_PATH)
