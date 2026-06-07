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
from homeassistant.helpers import entity_registry as er, label_registry as lr
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
    "{% set ns = namespace(rows=[]) -%}"
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
    "{%- set summary = '__SUMMARY__' -%}\n"
    "{%- set tracked = state_attr(summary, 'tracked_entities') or [] -%}\n"
    "{%- set silent = state_attr(summary, 'silent_entities') or [] -%}\n"
    "{%- if tracked -%}\n"
    "| Status | Entity | Last reported | Device |\n"
    "|---|---|---|---|\n"
    "{% for eid in tracked | sort -%}\n"
    "{% set did = device_id(eid) -%}\n"
    "{% set fn = state_attr(eid, 'friendly_name') -%}\n"
    "| {% if eid in silent %}🔴 silent{% else %}🟢 fresh{% endif %} "
    "| {% if fn %}{{ fn }}{% else %}`{{ eid }}`{% endif %} "
    "| {% if states[eid] and states[eid].last_reported %}{{ relative_time(states[eid].last_reported) }} ago{% else %}—{% endif %} "
    "| {% if did %}[Device](/config/devices/device/{{ did }}){% else %}—{% endif %} |\n"
    "{% endfor %}\n"
    "{% else %}\n"
    "No entities carry the label yet.\n"
    "{%- endif -%}\n"
)

_EXAMPLE_AUTOMATION = """\
{% raw %}
## Example automations

Two complementary templates — a daily morning report and an instant
alert on newly silent entities. Use either or both. Create one copy per
`(label, period)` combination; only the variables at the top need editing.

### Daily morning report

09:00 push listing every entity whose last report is older than the
configured watchdog period.

```yaml
alias: "Daily availability check: <label> / <period>"
description: >-
  Flags entities labeled '<label>' whose last_reported is older than <period>.

variables:
  watchdog_label: "Availability check: daily"
  watchdog_period: { hours: 24 }
  watchdog_period_text: "24h"
  notify_service: notify.mobile_app_pixel_6a

triggers:
  - trigger: time
    at: "09:00:00"

actions:
  - variables:
      stale_ids: >-
        {{ label_entities(watchdog_label)
           | expand
           | selectattr('last_reported', 'lt', now() - timedelta(**watchdog_period))
           | map(attribute='entity_id')
           | list }}
  - if:
      - condition: template
        value_template: "{{ stale_ids | count > 0 }}"
    then:
      - action: "{{ notify_service }}"
        data:
          title: "⚠️ {{ stale_ids | count }} device(s) silent >{{ watchdog_period_text }}"
          message: >-
            {% for eid in stale_ids -%}
            {%- set s = states[eid] -%}
            {%- set hrs = ((now() - s.last_reported).total_seconds() / 3600) | int -%}
            • {{ s.attributes.friendly_name or eid }} — {% if hrs < 48 %}{{ hrs }}h{% else %}{{ (hrs / 24) | int }}d{% endif %}
            {% endfor %}

mode: single
```

Adjust `watchdog_period` and `watchdog_period_text` per period:
`{minutes: 10}` / `"10m"`, `{hours: 1}` / `"1h"`, `{hours: 6}` / `"6h"`,
`{days: 7}` / `"7d"`. `watchdog_label` is the **display name** of the
Home Assistant label, not the slugified id.

### Instant alert on new silent entities

Fires whenever new entities are added to the watchdog's `silent_entities`
attribute. Notifies only about the diff (newly silent only), and
suppresses notifications during the first 10 min after an HA restart.

```yaml
alias: "Watchdog instant alert: <label> / <period>"
description: >-
  Notifies as soon as additional labeled entities go silent.
  Suppressed during the first 10 min after a Home Assistant restart.

variables:
  watchdog_period_text: "24h"
  notify_service: notify.mobile_app_pixel_6a

triggers:
  - trigger: state
    entity_id: sensor.important_entities_watchdog_silent_critical_24h
    attribute: silent_entities

conditions:
  # Restart guard: only fire 10 min after HA boot.
  # Requires the built-in Uptime integration (sensor.uptime). If it's
  # missing, the default keeps the automation active without protection.
  - condition: template
    value_template: >-
      {{ (now() - (states('sensor.uptime')
         | as_datetime(default=now() - timedelta(days=1)))).total_seconds() > 600 }}
  # Only fire when the silent count actually went up — skips swap cases.
  - condition: template
    value_template: >-
      {{ trigger.to_state.state | int(0) > trigger.from_state.state | int(0) }}

actions:
  - variables:
      previous: "{{ trigger.from_state.attributes.silent_entities or [] }}"
      current:  "{{ trigger.to_state.attributes.silent_entities or [] }}"
      newly_silent: "{{ current | reject('in', previous) | list }}"
  - action: "{{ notify_service }}"
    data:
      title: "⚠️ {{ newly_silent | count }} device(s): silent (>{{ watchdog_period_text }})"
      message: >-
        {% for eid in newly_silent -%}
        • {{ state_attr(eid, 'friendly_name') or eid }}
        {% endfor %}

mode: queued
max: 10
```

Replace `critical_24h` in the trigger's `entity_id` with your watchdog's
slug — the trigger's `entity_id` cannot be templated. Latency depends on
the watchdog's mode: *real-time* fires immediately when a source crosses
the threshold; *polling* fires at the next tick (`period / 10`).
{% endraw %}
"""

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

**Actions** (below, run across all configured watchdogs):
- **Recreate dashboards** rebuilds this entire dashboard from the current \
configuration. Press it after adding/removing watchdog entries or toggling \
real-time mode.
- **Clean orphans** removes binary-sensor registry entries whose source no \
longer carries its watchdog's label.
"""

_HEADER_INFO_TEMPLATE = (
    "{% set summary = '__SUMMARY__' %}"
    "**Label:** __LABEL__<br>"
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
    "**Last check:** {{ relative_time(states[summary].last_updated) }} ago"
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
    label_id: str,
    label_name: str,
    period: str,
    summary_eid: str,
) -> dict[str, Any]:
    """Build a sections view for one (label, period) entry.

    `label_id` is the registry slug — used for entity-id filters and the
    view path (URL stability). `label_name` is the human-readable label
    name from the label registry — used only for the displayed view title.
    """
    header_info = _HEADER_INFO_TEMPLATE.replace("__SUMMARY__", summary_eid).replace("__LABEL__", label_name)
    silent_now = _SILENT_NOW_TEMPLATE.replace("__SUMMARY__", summary_eid)
    all_tracked = _ALL_TRACKED_TEMPLATE.replace("__SUMMARY__", summary_eid)

    header_cards: list[dict[str, Any]] = [
        {
            "type": "markdown",
            "content": header_info,
        },
    ]

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
                    "filter": {"include": [{"entity_id": f"binary_sensor.watchdog_{slugify(label_id)}_*_{period}"}]},
                    "show_empty": False,
                    "grid_options": {"columns": 48, "rows": "auto"},
                }
            ],
            "column_span": 4,
        },
    ]

    return {
        "title": f"Watchdog {label_name}",
        "icon": "",
        "path": f"watchdog-{slugify(label_id)}-{period}",
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
    entries_data: list[tuple[str, str, str, str]],
    create_dashboard_eid: str | None,
    clean_orphans_eid: str | None,
) -> dict[str, Any]:
    """Build a top-level overview view.

    Sections, in order:
    1. Explanation of what the dashboard does (always shown).
    2. Tiles per configured watchdog (or "no entries" hint).
    3. Global actions (Recreate dashboards, Clean orphans) when their
       button entities exist. Each runs across all configured watchdogs.
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
        for label_id, label_name, period, summary_eid in entries_data:
            tile_cards.append(
                {
                    "type": "tile",
                    "entity": summary_eid,
                    "name": f"{label_name} ({period})",
                    "color": "orange",
                    "tap_action": {
                        "action": "navigate",
                        "navigation_path": f"/{DASHBOARD_URL_PATH}/watchdog-{slugify(label_id)}-{period}",
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

    action_buttons: list[dict[str, Any]] = []
    if create_dashboard_eid:
        action_buttons.append(
            {
                "type": "button",
                "entity": create_dashboard_eid,
                "name": "Recreate dashboards",
                "icon": "mdi:view-dashboard-edit",
                "show_state": False,
            }
        )
    if clean_orphans_eid:
        action_buttons.append(
            {
                "type": "button",
                "entity": clean_orphans_eid,
                "name": "Clean orphans",
                "icon": "mdi:broom",
                "show_state": False,
            }
        )
    if action_buttons:
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
                    *action_buttons,
                ],
            }
        )

    sections.append(
        {
            "type": "grid",
            "cards": [
                {
                    "type": "markdown",
                    "content": _EXAMPLE_AUTOMATION,
                    "grid_options": {"columns": 48, "rows": "auto"},
                }
            ],
            "column_span": 4,
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
    label_reg = lr.async_get(hass)
    detail_views: list[dict[str, Any]] = []
    entries_data: list[tuple[str, str, str, str]] = []
    overview_create_dashboard_eid: str | None = None
    overview_clean_orphans_eid: str | None = None

    for entry in entries:
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator is None:
            continue

        summary_eid, clean_orphans_eid, create_dashboard_eid = _get_entry_key_entities(hass, entry)
        if summary_eid is None:
            _LOGGER.warning("No summary sensor found for entry %s; skipping view", entry.entry_id)
            continue

        # Recreate-Dashboards and Clean-Orphans are global actions — every
        # entry exposes its own button entity, but pressing any of them
        # spans all watchdogs. Pick the first one we encounter so the
        # Overview hosts each action once.
        if overview_create_dashboard_eid is None and create_dashboard_eid is not None:
            overview_create_dashboard_eid = create_dashboard_eid
        if overview_clean_orphans_eid is None and clean_orphans_eid is not None:
            overview_clean_orphans_eid = clean_orphans_eid

        # Display the human-readable label name when available; fall back
        # to the label_id for any orphaned entry whose label has been
        # deleted from the registry.
        label_obj = label_reg.async_get_label(coordinator.label_id)
        label_name = label_obj.name if label_obj else coordinator.label_id

        entries_data.append((coordinator.label_id, label_name, coordinator.period_key, summary_eid))
        detail_views.append(
            _build_view(
                coordinator.label_id,
                label_name,
                coordinator.period_key,
                summary_eid,
            )
        )

    return {
        "title": DASHBOARD_TITLE,
        "views": [
            _build_overview_view(
                entries_data,
                overview_create_dashboard_eid,
                overview_clean_orphans_eid,
            ),
            *detail_views,
        ],
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
    )

    await lovelace_data.dashboards[DASHBOARD_URL_PATH].async_save(config)
    _LOGGER.info("Created Watchdog dashboard at /%s", DASHBOARD_URL_PATH)
