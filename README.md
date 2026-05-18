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
2. Add the integration. Pick the label and a period (10m, 1h, 6h, 12h, 24h, 7d).
3. Repeat for additional `(label, period)` combinations if you want
   different thresholds for different groups of devices.

The period can be changed later via the integration's Configure button
without losing history (entities keep their unique_id across reloads).

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

The integration reacts to source updates immediately (via state-change and
state-report events) and re-evaluates every 60 s so silent entities flip
within at most one minute of crossing the threshold.

## Example automation

Daily 9am notification of silent entities:

```yaml
alias: Daily silent device report
triggers:
  - trigger: time
    at: "09:00:00"
actions:
  - if:
      - condition: numeric_state
        entity_id: sensor.important_entities_watchdog_silent_critical_24h
        above: 0
    then:
      - action: notify.mobile_app_pixel_6a
        data:
          title: >-
            {{ states('sensor.important_entities_watchdog_silent_critical_24h') }}
            device(s) silent >24h
          message: >-
            {{ state_attr('sensor.important_entities_watchdog_silent_critical_24h',
                          'silent_entities')
               | map('state_attr', 'friendly_name') | list | join(', ') }}
```

## Known limitations / things to verify

- **Restart day false positives.** After an HA restart, `last_reported`
  resets. Entities will look stale until they next report. Acceptable for
  most use cases; if it matters, add an uptime grace condition to your
  notification.
- **Coordinator tick interval.** Hard-coded to 60 seconds. Sufficient for
  hour-scale periods. Reduce if you ever use periods under 5 minutes
  (not currently exposed via UI).
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
