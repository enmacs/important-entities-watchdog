"""Config flow for Important Entities Watchdog."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, label_registry as lr
from homeassistant.helpers.selector import DurationSelector, DurationSelectorConfig

from .const import (
    CONF_LABEL,
    CONF_PERIOD,
    CONF_REALTIME,
    DEFAULT_PERIOD_SECONDS,
    DEFAULT_REALTIME,
    DOMAIN,
    MIN_PERIOD_SECONDS,
)
from .duration import format_period, seconds_to_duration_dict

# Free-form duration input (days/hours/minutes/seconds). Stored as seconds.
_PERIOD_SELECTOR = DurationSelector(DurationSelectorConfig(enable_day=True))


def _period_seconds(value: Any) -> int:
    """Convert a DurationSelector value to total seconds."""
    return int(cv.time_period_dict(value).total_seconds())


class WatchdogConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Important Entities Watchdog."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        label_reg = lr.async_get(self.hass)
        labels = {lbl.label_id: lbl.name for lbl in label_reg.async_list_labels()}

        if not labels:
            return self.async_abort(reason="no_labels")

        if user_input is not None:
            period_seconds = _period_seconds(user_input[CONF_PERIOD])
            if period_seconds < MIN_PERIOD_SECONDS:
                errors[CONF_PERIOD] = "period_too_short"
            else:
                slug = format_period(period_seconds)
                await self.async_set_unique_id(f"{user_input[CONF_LABEL]}_{slug}")
                self._abort_if_unique_id_configured()

                label = label_reg.async_get_label(user_input[CONF_LABEL])
                label_name = label.name if label else user_input[CONF_LABEL]
                return self.async_create_entry(
                    title=f"{label_name} ({slug})",
                    data={
                        CONF_LABEL: user_input[CONF_LABEL],
                        CONF_PERIOD: period_seconds,
                        CONF_REALTIME: user_input[CONF_REALTIME],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_LABEL): vol.In(labels),
                vol.Required(CONF_PERIOD, default=seconds_to_duration_dict(DEFAULT_PERIOD_SECONDS)): _PERIOD_SELECTOR,
                vol.Required(CONF_REALTIME, default=DEFAULT_REALTIME): bool,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> WatchdogOptionsFlow:
        """Return the options flow."""
        return WatchdogOptionsFlow()


class WatchdogOptionsFlow(config_entries.OptionsFlow):
    """Options flow for changing the period and real-time mode.

    Note: self.config_entry is provided by the base class as a property in
    modern HA. Do not assign it in __init__ — that path is deprecated.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            period_seconds = _period_seconds(user_input[CONF_PERIOD])
            if period_seconds < MIN_PERIOD_SECONDS:
                errors[CONF_PERIOD] = "period_too_short"
            else:
                return self.async_create_entry(
                    title="",
                    data={CONF_PERIOD: period_seconds, CONF_REALTIME: user_input[CONF_REALTIME]},
                )

        current_seconds = int(self.config_entry.options.get(CONF_PERIOD, self.config_entry.data[CONF_PERIOD]))
        current_realtime = self.config_entry.options.get(
            CONF_REALTIME, self.config_entry.data.get(CONF_REALTIME, DEFAULT_REALTIME)
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_PERIOD, default=seconds_to_duration_dict(current_seconds)): _PERIOD_SELECTOR,
                vol.Required(CONF_REALTIME, default=current_realtime): bool,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )
