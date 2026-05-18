"""Config flow for Important Entities Watchdog."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import label_registry as lr

from .const import CONF_LABEL, CONF_PERIOD, DEFAULT_PERIOD, DOMAIN, PERIOD_OPTIONS


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
            unique_id = f"{user_input[CONF_LABEL]}_{user_input[CONF_PERIOD]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            label = label_reg.async_get_label(user_input[CONF_LABEL])
            label_name = label.name if label else user_input[CONF_LABEL]
            title = f"{label_name} ({user_input[CONF_PERIOD]})"

            return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_LABEL): vol.In(labels),
                vol.Required(CONF_PERIOD, default=DEFAULT_PERIOD): vol.In(list(PERIOD_OPTIONS)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> WatchdogOptionsFlow:
        """Return the options flow."""
        return WatchdogOptionsFlow()


class WatchdogOptionsFlow(config_entries.OptionsFlow):
    """Options flow for changing the period.

    Note: self.config_entry is provided by the base class as a property in
    modern HA. Do not assign it in __init__ — that path is deprecated.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(CONF_PERIOD, self.config_entry.data[CONF_PERIOD])
        schema = vol.Schema(
            {
                vol.Required(CONF_PERIOD, default=current): vol.In(list(PERIOD_OPTIONS)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
