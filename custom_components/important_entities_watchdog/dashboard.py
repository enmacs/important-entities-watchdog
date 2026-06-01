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


_SILENT_NOW_TEMPLATE = (
    "{%- set summary = '__SUMMARY__' -%}"
    "{%- set silent = state_attr(summary, 'silent_entities') or [] -%}"
    "{%- if silent -%}"
    "**{{ silent | count }} silent**\n\n"
    "| Status | Entity | Last reported | Device |\n"
    "|---|---|---|---|\n"
    "{%- set ns = namespace(rows=[]) -%}"
    "{%- for eid in silent -%}"
    "{%- set ts = states[eid].last_reported.timestamp() if states[eid] and states[eid].last_reported else 0 -%}"
    "{%- set ns.rows = ns.rows + [{'eid': eid, 'ts': ts}] -%}"
    "{%- endfor -%}"
    "{%- for row in ns.rows | sort(attribute='ts') -%}"
    "{%- set eid = row.eid -%}"
    "{%- set did = device_id(eid) -%}"
    "{%- set fn = state_attr(eid, 'friendly_name') -%}"
    "| 🔴 "
    "| {% if fn %}{{ fn }}{% else %}`{{ eid }}`{% endif %} "
    "| {% if states[eid] and states[eid].last_reported %}{{ relative_time(states[eid].last_reported) }} ago{% else %}—{% endif %} "
    "| {% if did %}[Device](/config/devices/device/{{ did }}){% else %}—{% endif %} |\n"
    "{%- endfor -%}"
    "{%- else -%}"
    "All tracked entities reporting within period."
    "{%- endif -%}"
)

_ALL_TRACKED_TEMPLATE = (
    "{%- set summary = '__SUMMARY__' -%}"
    "{%- set tracked = state_attr(summary, 'tracked_entities') or [] -%}"
    "{%- set silent = state_attr(summary, 'silent_entities') or [] -%}"
    "{%- if tracked -%}"
    "| Status | Entity | Last reported | Device |\n"
    "|---|---|---|---|\n"
    "{%- for eid in tracked | sort -%}"
    "{%- set did = device_id(eid) -%}"
    "{%- set fn = state_attr(eid, 'friendly_name') -%}"
    "| {% if eid in silent %}🔴 silent{% else %}🟢 fresh{% endif %} "
    "| {% if fn %}{{ fn }}{% else %}`{{ eid }}`{% endif %} "
    "| {% if states[eid] and states[eid].last_reported %}{{ relative_time(states[eid].last_reported) }} ago{% else %}—{% endif %} "
    "| {% if did %}[Device](/config/devices/device/{{ did }}){% else %}—{% endif %} |\n"
    "{%- endfor -%}"
    "{%- else -%}"
    "No entities carry the label yet."
    "{%- endif -%}"
)

_OVERVIEW_EXPLANATION = """\
## About Entity Watchdog

This dashboard monitors entities labeled in Home Assistant and flags those \
that haven't reported within a configured period.

Each tab below corresponds to one **watchdog** — a pair of *label* (entity \
group) and *silent threshold* (period). The integration creates one binary \
sensor per labeled entity that flips to **off** once the source goes silent \
for longer than the threshold.

**Badges per watchdog tab:**
- 🔴 **Silent (period)** — count of entities not reporting within the period
- **Tracked entities** — total entities currently carrying the label

**Operating modes** (set per watchdog under Configure):
- **Polling** *(default)* — periodic re-check every `period / 10`. Cheap, \
no event subscription. Detection latency up to one tick.
- **Real-time** — subscribes to every source state event. Use only for \
short periods where you need instant feedback.

**Actions:**
- Each watchdog tab has its own **Clean orphans** button to remove \
binary-sensor registry entries whose source no longer carries the label.
- **Recreate dashboards** (below) rebuilds this entire dashboard from the \
current configuration. Press it after adding/removing watchdog entries or \
toggling real-time mode.
"""

_HEADER_INFO_TEMPLATE = (
    "{% set summary = '__SUMMARY__' %}"
    "**Mode:** {{ 'Real-time' if state_attr(summary, 'realtime') else 'Polling' }}<br>"
    "{% set ti = state_attr(summary, 'tick_seconds') %}"
    "{% if ti %}**Check interval:** every "
    "{% if ti < 90 %}{{ ti }} second{% if ti != 1 %}s{% endif %}"
    "{% elif ti < 5400 %}"
    "{% set ti_mins = (ti / 60) | round | int %}"
    "{{ ti_mins }} minute{% if ti_mins != 1 %}s{% endif %}"
    "{% else %}"
    "{% set ti_hours = (ti / 3600) | round(1) %}"
    "{{ ti_hours }} hour{% if ti_hours != 1.0 %}s{% endif %}"
    "{% endif %}<br>"
    "{% endif %}"
    "**Last update:** {{ relative_time(states[summary].last_updated) }} ago"
    "{% set nc = state_attr(summary, 'next_check') %}"
    "{% if nc %}<br>**Next check:** "
    "{% set secs = ((as_timestamp(nc) - as_timestamp(now())) | int) %}"
    "{% if secs <= 0 %}due now"
    "{% elif secs < 90 %}in {{ secs }} second{% if secs != 1 %}s{% endif %}"
    "{% elif secs < 5400 %}"
    "{% set mins = (secs / 60) | round | int %}"
    "in {{ mins }} minute{% if mins != 1 %}s{% endif %}"
    "{% else %}"
    "{% set hours = (secs / 3600) | round(1) %}"
    "in {{ hours }} hour{% if hours != 1.0 %}s{% endif %}"
    "{% endif %}"
    "{% endif %}"
)


def _get_entry_key_entities(hass: HomeAssistant, entry: ConfigEntry) -> tuple[str | None, str | None, str | None]:
    """Return (summary_sensor_id, clean_orphans_button_id, create_dashboard_button_id)."""
    ent_reg = er.async_get(hass)
    summary: str | None = None
    clean_orphans: str | None = None
    create_dashboard: str | None = None
    for ent in ent_reg.entities.values():
        if ent.config_entry_id != entry.entry_id:
            continue
        if ent.domain == "sensor" and ent.entity_category is None:
            summary = ent.entity_id
        elif ent.domain == "button" and ent.entity_category == EntityCategory.CONFIG:
            if ent.unique_id.endswith("_clean_orphans"):
                clean_orphans = ent.entity_id
            elif ent.unique_id.endswith("_create_dashboard"):
                create_dashboard = ent.entity_id
    return summary, clean_orphans, create_dashboard


def _build_view(
    label: str,
    period: str,
    summary_eid: str,
    clean_orphans_eid: str | None,
) -> dict[str, Any]:
    """Build a sections view for one (label, period) entry."""
    header_info = _HEADER_INFO_TEMPLATE.replace("__SUMMARY__", summary_eid)
    silent_now = _SILENT_NOW_TEMPLATE.replace("__SUMMARY__", summary_eid)
    all_tracked = _ALL_TRACKED_TEMPLATE.replace("__SUMMARY__", summary_eid)

    header_cards: list[dict[str, Any]] = [
        {
            "type": "markdown",
            "content": header_info,
        },
    ]

    action_cards: list[dict[str, Any]] = []
    if clean_orphans_eid:
        action_cards.append(
            {
                "type": "button",
                "entity": clean_orphans_eid,
                "name": "Clean orphans",
                "icon": "mdi:broom",
                "show_state": False,
            }
        )

    sections: list[dict[str, Any]] = [
        {"type": "grid", "cards": header_cards},
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
    ]
    if action_cards:
        sections.append(
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "heading",
                        "icon": "mdi:tools",
                        "heading": "Actions",
                        "heading_style": "subtitle",
                    },
                    *action_cards,
                ],
            }
        )

    return {
        "title": f"Watchdog {label} {period}",
        "icon": "",
        "path": f"watchdog-{slugify(label)}-{period}",
        "type": "sections",
        "badges": [
            {
                "type": "entity",
                "entity": summary_eid,
                "name": f"Silent ({period})",
                "color": "orange",
                "show_name": True,
                "show_state": True,
            },
            {
                "type": "entity",
                "entity": summary_eid,
                "name": "Tracked entities",
                "icon": "mdi:counter",
                "state_content": "tracked_count",
                "show_name": True,
                "show_state": True,
            },
        ],
        "sections": sections,
        "max_columns": 4,
        "cards": [],
    }


def _build_overview_view(
    entries_data: list[tuple[str, str, str]],
    create_dashboard_eid: str | None,
) -> dict[str, Any]:
    """Build a top-level overview view.

    Sections, in order:
    1. Explanation of what the dashboard does (always shown).
    2. Tiles per configured watchdog (or "no entries" hint).
    3. Global "Recreate dashboards" action (when the button entity exists).
    """
    sections: list[dict[str, Any]] = [
        {
            "type": "grid",
            "cards": [
                {
                    "type": "markdown",
                    "content": _OVERVIEW_EXPLANATION,
                    "grid_options": {"columns": 48, "rows": "auto"},
                }
            ],
            "column_span": 4,
        }
    ]

    if entries_data:
        tile_cards: list[dict[str, Any]] = [
            {
                "type": "heading",
                "icon": "mdi:radar",
                "heading": "All watchdogs",
                "heading_style": "title",
            }
        ]
        for label, period, summary_eid in entries_data:
            tile_cards.append(
                {
                    "type": "tile",
                    "entity": summary_eid,
                    "name": f"{label} ({period})",
                    "color": "orange",
                    "tap_action": {
                        "action": "navigate",
                        "navigation_path": f"/{DASHBOARD_URL_PATH}/watchdog-{slugify(label)}-{period}",
                    },
                }
            )
        sections.append({"type": "grid", "cards": tile_cards})
    else:
        sections.append(
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "markdown",
                        "content": "_No watchdog entries configured yet. Add a configuration entry first._",
                    }
                ],
            }
        )

    if create_dashboard_eid:
        sections.append(
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "heading",
                        "icon": "mdi:tools",
                        "heading": "Actions",
                        "heading_style": "subtitle",
                    },
                    {
                        "type": "button",
                        "entity": create_dashboard_eid,
                        "name": "Recreate dashboards",
                        "icon": "mdi:view-dashboard-edit",
                        "show_state": False,
                    },
                ],
            }
        )

    return {
        "title": "Overview",
        "icon": "mdi:radar",
        "path": "overview",
        "type": "sections",
        "sections": sections,
        "max_columns": 4,
        "cards": [],
    }


def _generate_lovelace_config(hass: HomeAssistant) -> dict[str, Any]:
    """Build a Lovelace dashboard config from all active config entries."""
    entries = hass.config_entries.async_entries(DOMAIN)
    detail_views: list[dict[str, Any]] = []
    entries_data: list[tuple[str, str, str]] = []
    overview_create_dashboard_eid: str | None = None

    for entry in entries:
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator is None:
            continue

        summary_eid, clean_orphans_eid, create_dashboard_eid = _get_entry_key_entities(hass, entry)
        if summary_eid is None:
            _LOGGER.warning("No summary sensor found for entry %s; skipping view", entry.entry_id)
            continue

        # The Recreate Dashboards button is a global action — every entry's
        # button rebuilds the whole dashboard. Pick the first one we find
        # so the Overview can host it once instead of once per watchdog.
        if overview_create_dashboard_eid is None and create_dashboard_eid is not None:
            overview_create_dashboard_eid = create_dashboard_eid

        entries_data.append((coordinator.label_id, coordinator.period_key, summary_eid))
        detail_views.append(
            _build_view(
                coordinator.label_id,
                coordinator.period_key,
                summary_eid,
                clean_orphans_eid,
            )
        )

    return {
        "title": DASHBOARD_TITLE,
        "views": [_build_overview_view(entries_data, overview_create_dashboard_eid), *detail_views],
    }


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
