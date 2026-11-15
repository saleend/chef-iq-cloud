"""Email login or local session import; never persist the password."""

import json
from pathlib import Path

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import DOMAIN
from .cloud import AuthError, login, refresh

CONFIG = json.loads(Path(__file__).with_name("app_config.json").read_text())


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

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
                    auth = await refresh(session, CONFIG["firebase_api_key"], data["refresh_token"])
                    refresh_token = auth["refresh_token"]
                    user_id = auth["user_id"]
                else:
                    auth = await login(
                        session,
                        CONFIG["firebase_api_key"],
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
                        "firebase_api_key": CONFIG["firebase_api_key"],
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
                    vol.Optional("password", default=""): str,
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
                    CONFIG["firebase_api_key"],
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
            data_schema=vol.Schema({vol.Required("email"): str, vol.Required("password"): str}),
            errors=errors,
        )
