"""Email login or local session import; never persist the password."""

import json
from pathlib import Path

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from . import DOMAIN
from .cloud import AuthError, login, refresh
from .const import CONF_ENABLE_COOK_CONTROLS, FIREBASE_API_KEY


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return CookOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                session = async_get_clientsession(self.hass)
                if user_input.get("use_saved_session", False):
                    path = Path(self.hass.config.path("chef_iq_cloud_session.json"))
                    data = await self.hass.async_add_executor_job(
                        lambda: json.loads(path.read_text())
                    )
                    auth = await refresh(session, FIREBASE_API_KEY, data["refresh_token"])
                    refresh_token = auth["refresh_token"]
                    user_id = auth["user_id"]
                else:
                    auth = await login(
                        session,
                        FIREBASE_API_KEY,
                        user_input.get("email", ""),
                        user_input.get("password", ""),
                    )
                    refresh_token = auth["refreshToken"]
                    user_id = auth["localId"]
                await self.async_set_unique_id(user_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="CHEF iQ Cloud + Bluetooth",
                    data={
                        "firebase_api_key": FIREBASE_API_KEY,
                        "refresh_token": refresh_token,
                        "user_id": user_id,
                    },
                )
            except (OSError, ValueError, KeyError):
                errors["base"] = "session_missing"
            except AuthError:
                errors["base"] = "invalid_auth"
            except AbortFlow:
                raise
            except Exception:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional("use_saved_session", default=False): bool,
                    vol.Optional("email", default=""): str,
                    vol.Optional("password", default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input:
            try:
                auth = await login(
                    async_get_clientsession(self.hass),
                    FIREBASE_API_KEY,
                    user_input["email"],
                    user_input["password"],
                )
                entry = self._get_reauth_entry()
                if auth["localId"] != entry.data["user_id"]:
                    errors["base"] = "wrong_account"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={"refresh_token": auth["refreshToken"]}
                    )
            except Exception:
                errors["base"] = "invalid_auth"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("email"): str,
                    vol.Required("password"): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )


class CookOptionsFlow(config_entries.OptionsFlowWithReload):
    async def async_step_init(self, user_input=None):
        options = self.config_entry.options
        if user_input is not None:
            return self.async_create_entry(data={**options, **user_input})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLE_COOK_CONTROLS,
                        default=options.get(CONF_ENABLE_COOK_CONTROLS, False),
                    ): bool,
                }
            ),
        )
