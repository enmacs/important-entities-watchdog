# Important Entities Watchdog

A Home Assistant custom integration that flags labeled entities which haven't
reported within a configurable period. Useful for noticing dead Zigbee
batteries, dropped WiFi devices, expired cloud tokens, and other silent
failures before they bite you.

## How it works

- You create a label in Home Assistant (e.g. `Availability check: daily`)
  and apply it to the entities you care about.
- You add a config entry per `(label, period)` pair you want to track.
- For each labeled entity, the integration creates a
  `binary_sensor.important_entities_watchdog_<label>_<source>_<period>`
  with `device_class: connectivity` — `on` if the source reported within
  the configured period, `off` if not.
- A summary
  `sensor.important_entities_watchdog_silent_<label>_<period>` exposes the
  current count and a `silent_entities` attribute listing the entity_ids
  that are silent.
- Membership is dynamic: label or unlabel an entity in the UI and the
  corresponding sensors appear / disappear automatically.

The staleness check uses each entity's `last_reported` timestamp (falling
back to `last_updated` on older HA versions). This catches devices that
report unchanging values — a temperature sensor stuck at "21.0°C" looks
fresh to a `last_changed` check but stale to `last_reported`.

## Installation

### Manual

1. Copy `custom_components/important_entities_watchdog/` into your HA
   `config/custom_components/` directory.
2. Restart Home Assistant.
3. Settings → Devices & Services → Add Integration → "Important Entities
   Watchdog".

### Via HACS (when published)

1. HACS → Integrations → Custom repositories → add this repository URL,
   category "Integration".
2. Install, restart, add integration.

## Configuration

You configure one entry per `(label, period)` combination:

1. Create the label in HA (Settings → Labels) and apply it to the
   entities you want to watch.
2. Add the integration. Pick the label, a period (10m, 1h, 6h, 12h, 24h, 7d),
   and optionally enable **Real-time mode**.
3. Repeat for additional `(label, period)` combinations if you want
   different thresholds for different groups of devices.

Period and real-time mode can be changed later via the integration's
Configure button without losing history (entities keep their unique_id
across reloads).

## Sensors created per config entry

For a label `critical` (label_id) with period "24h" applied to N entities,
the integration creates:

- N × `binary_sensor.important_entities_watchdog_critical_<source>_24h`
  — ON when fresh, OFF when silent
- 1 × `sensor.important_entities_watchdog_silent_critical_24h` — count of
  silent entities
- 1 × `button.important_entities_watchdog_clean_orphans_critical_24h` —
  removes binary_sensor registry entries whose source is no longer labeled.
  Valid sensors keep their history, friendly names, and area assignments.
  Filed under the Config entity category so it stays out of dashboards.

Attributes on the summary sensor include `silent_entities`,
`tracked_entities`, `tracked_count`, `period`, and `label_id`.

### Real-time mode vs. polling

Two evaluation modes are available, chosen per config entry:

- **Real-time mode (opt-in).** The integration subscribes to state-change
  and state-report events for every tracked source and updates the
  matching binary sensor immediately. A 60 s tick covers the
  "going silent" case (no event fires when a device simply stops
  reporting). Use this for short periods (≤ 1 h) or when you want the
  UI to flip the instant a source comes back online.
- **Polling mode (default).** No event subscription. The integration
  re-evaluates all binary sensors on a tick of `period / 10` — e.g.
  every ~2.4 h for a 24 h period, every 6 min for a 1 h period, every
  60 s for a 10 min period. Detection of a stale or returned source
  is delayed by at most one tick. Dramatically cheaper for
  high-frequency sources (a sensor that reports every second would
  otherwise trigger a state-write per second in real-time mode).

The freshness check itself is identical in both modes: it compares
`now - state.last_reported` against the configured period. The mode
only changes *when* that comparison runs.

## Example automations

Two complementary templates: a daily morning report listing everything
currently silent, and an instant alert that fires whenever a new entity
goes silent. Use either or both. Create one copy per `(label, period)`
combination — only the variables at the top need editing.

### Daily morning report

A 09:00 push notification listing every labeled entity whose last report
is older than the configured watchdog period:

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
Home Assistant label (e.g. `Availability check: daily`), not the
slugified id. The template reads entities by label and compares
`last_reported` directly, so the same automation works regardless of
which watchdog entry covers them.

### Instant alert on new silent entities

Fires whenever the watchdog's summary sensor adds new entries to its
`silent_entities` attribute, so a push arrives as soon as something
goes silent — no need to wait for the morning report. Notifies only
about the **newly** silent entities (diff against the previous state)
and suppresses notifications during the first 10 minutes after a Home
Assistant restart (when `last_reported` is briefly empty for everyone):

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
  # Only fire when the silent count actually went up — skips swap cases
  # where one entity returns while another goes silent.
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
slug. The trigger's `entity_id` cannot be templated, so the summary
sensor reference lives in the trigger itself rather than in
`variables:`. Latency depends on the watchdog's mode: *real-time* fires
the moment a source crosses the threshold; *polling* fires at the next
tick (`period / 10`).

## Known limitations / things to verify

- **Restart day false positives.** After an HA restart, `last_reported`
  resets. Entities will look stale until they next report. Acceptable for
  most use cases; if it matters, add an uptime grace condition to your
  notification.
- **Polling mode detection delay.** In polling mode the tick is
  `period / 10`, so a stale entity is detected up to that delay after
  crossing the threshold. Enable real-time mode if you need faster
  reaction.
- **Per-entity uptime % is not yet implemented.** Planned for a later
  version, likely via programmatic `history_stats` integration.
- **HA event names.** This integration listens for
  `entity_registry_updated` and `label_registry_updated`. These are
  stable but if a future HA version renames them, update `coordinator.py`.
- **`integration_type`.** Set to `service`. This is appropriate because
  the integration doesn't represent a physical device or hub.

## Development

Tested against Home Assistant 2024.x and 2025.x.

To run against a dev HA instance:

1. Use the official Home Assistant Core devcontainer.
2. Symlink `custom_components/important_entities_watchdog` into your dev
   instance's `config/custom_components/` directory.
3. Enable debug logging:

   ```yaml
   logger:
     default: info
     logs:
       custom_components.important_entities_watchdog: debug
   ```

## Manual test plan

1. Create a label "Watchdog test" in HA.
2. Apply it to 2-3 entities.
3. Add the integration with the test label and period "1h".
4. Verify binary sensors and the summary sensor appear.
5. Wait for the source entities to be quiet for >1h, or fake it by
   restarting HA and waiting.
6. Verify the binary sensors flip and the summary count updates.
7. Add the label to one more entity; verify a new binary sensor appears
   within ~1 minute.
8. Remove the label from one entity; verify its binary sensor disappears.
9. Use Configure to change the period to "24h"; verify entities reload
   and history is preserved.
10. Delete the config entry; verify all related entities are removed
    from the entity registry.

## License

MIT.
