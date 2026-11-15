"""CHEF iQ cloud readings and fresh-source aggregation."""

import asyncio
import logging
import time
import uuid
from datetime import timedelta

from homeassistant.components import persistent_notification
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .cloud import AuthError, json_request, refresh, stream
from .cook_sync import StartTransaction, reconcile_journal
from .cooks import start_payload
from .history import HistoryClient, history_body
from .selection import timestamp

DOMAIN = "chef_iq_cloud"
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry):
    manager = Manager(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    manager.cook_journal = await manager.store.async_load() or {}
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.SENSOR, Platform.NUMBER, Platform.TEXT, Platform.BUTTON]
    )
    manager.task = entry.async_create_background_task(hass, manager.run(), "CHEF iQ cloud listener")
    entry.async_on_unload(async_track_time_interval(hass, manager.tick, timedelta(seconds=15)))
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, manager.stop))
    return True


async def async_unload_entry(hass, entry):
    ok = await hass.config_entries.async_unload_platforms(
        entry, [Platform.SENSOR, Platform.NUMBER, Platform.TEXT, Platform.BUTTON]
    )
    if ok:
        manager = hass.data[DOMAIN].pop(entry.entry_id)
        manager.stop()
        if manager.task:
            try:
                await manager.task
            except asyncio.CancelledError:
                pass
    return ok


class Manager:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.probes = {}
        self.listeners = []
        self.connected = False
        self.stop_event = asyncio.Event()
        self.task = None
        self.last_error = None
        self.devices = []
        self.sessions = {}
        self.hub_state = {}
        self.pending = {}
        self.sender = None
        self.settings = {a: dict(v) for a, v in entry.options.get("cook_settings", {}).items()}
        self.last_full = 0
        self.cook_lock = asyncio.Lock()
        self.seen_events = set()
        self.signal = DOMAIN + "_" + entry.entry_id
        self.store = Store(hass, 1, DOMAIN + "_" + entry.entry_id + "_cook_journal")
        self.cook_journal = {}
        self.auth_headers = None
        self.user_id = None
        self.controls_fault = False

    @callback
    def stop(self, event=None):
        self.stop_event.set()
        if self.task:
            self.task.cancel()

    @callback
    def tick(self, now=None):
        self.notify()
        if self.connected and time.time() - self.last_full > 60:
            self.last_full = time.time()
            self.hass.async_create_task(self.refresh_cooks())

    @callback
    def notify(self):
        async_dispatcher_send(self.hass, self.signal)

    @callback
    def connection(self, value):
        self.connected = value
        if not value:
            self.sender = None
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(
                        HomeAssistantError("CHEF iQ disconnected; check the app before retrying")
                    )
        self.notify()

    def ready(self, sender):
        self.sender = sender
        self.hass.async_create_task(self.refresh_cooks())

    async def request(self, device, command, data):
        if not self.connected or not self.sender:
            raise HomeAssistantError("CHEF iQ hub is not connected")
        rid = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        try:
            await self.sender(device, command, data, rid)
            result = await asyncio.wait_for(future, 20)
            if result.get("status", {}).get("code") != 0:
                raise HomeAssistantError(
                    "Hub rejected the command (code "
                    + str(result.get("status", {}).get("code"))
                    + ")"
                )
            return result
        except asyncio.TimeoutError:
            raise HomeAssistantError(
                "No hub acknowledgement; check the app before retrying"
            ) from None
        finally:
            self.pending.pop(rid, None)

    async def refresh_cooks(self, strict=False):
        try:
            for d in self.devices:
                await self.request(d["device_id"], "get-state", {})
            self.last_full = time.time()
        except HomeAssistantError as err:
            self.last_error = type(err).__name__
            if strict:
                raise

    def set_setting(self, address, key, value):
        self.settings[address][key] = value
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, "cook_settings": self.settings}
        )

    def cook_for(self, address):
        return next(
            (x for x in self.sessions.values() if x.get("probe_address", "").upper() == address),
            None,
        )

    async def reconcile_starts(self):
        async with self.cook_lock:
            if not self.auth_headers or not self.user_id:
                raise HomeAssistantError("Account authentication is not ready")
            if not self.connected or not self.devices:
                raise HomeAssistantError("Hub connection is not ready")
            sessions = []
            for device in self.devices:
                response = await self.request(device["device_id"], "get-state", {})
                data = response.get("data", {})
                if not isinstance(data.get("sessions"), list):
                    raise HomeAssistantError("Fresh full hub state is required")
                sessions.extend(data["sessions"])
            history = HistoryClient(async_get_clientsession(self.hass), self.auth_headers)
            # All hubs were freshly queried; absent sessions can be marked resolved
            # only by this explicit check. No creation or cancellation is replayed.
            result = await reconcile_journal(
                self.cook_journal, {"sessions": sessions}, history, self.user_id
            )
            await self.store.async_save(result)
            self.cook_journal = result
            self.notify()

    async def start_cook(self, address):
        async with self.cook_lock:
            if self.controls_fault or not self.auth_headers:
                raise HomeAssistantError("Cook control unavailable; inspect the hub and app")
            probe = self.probes.get(address, {})
            device = probe.get("hub_id")
            hub = next((d for d in self.devices if d["device_id"] == device), None)
            if not hub:
                raise HomeAssistantError("Probe hub not found")

            async def read():
                return (await self.request(device, "get-state", {}))["data"]

            before = await read()
            key = before.get("user_info", {}).get("notification_key")
            if not key:
                raise HomeAssistantError("Hub notification route unavailable")
            setting = self.settings[address]
            try:
                payload = start_payload(
                    address,
                    probe.get("number", 0),
                    setting["name"],
                    setting["target"],
                    key,
                    flip=setting["flip"] or None,
                    wrap=setting["wrap"] or None,
                    rest=setting["rest"],
                )
            except ValueError as err:
                raise HomeAssistantError(str(err)) from None
            app_data = {
                k: v
                for k, v in payload.items()
                if k not in ("session_id", "notification_key", "auto_cancel")
            }
            app_data["cooking_state_notifications"] = app_data["cooking_state_notifications"][:-1]
            app_data["probe_nickname"] = probe.get("name", f"Probe {probe.get('number', 0)}")
            body = history_body(
                app_data,
                hub["model_number"],
                device,
                hub.get("name", hub.get("device_name", "CHEF iQ hub")),
                payload["session_id"],
            )

            async def save(data):
                self.cook_journal = data
                await self.store.async_save(data)

            async def send(data):
                await self.request(device, "start-session", data)

            history = HistoryClient(async_get_clientsession(self.hass), self.auth_headers)
            tx = StartTransaction(read, send, history, save, self.cook_journal, self.user_id)
            try:
                await tx.start(
                    payload,
                    body,
                    allowed_existing_session_ids=[
                        s["session_id"] for s in before.get("sessions", [])
                    ],
                )
            except Exception as err:
                raise HomeAssistantError(
                    "Cook start not fully verified; check the CHEF iQ app before retrying ("
                    + type(err).__name__
                    + ")"
                ) from None
            await self.refresh_cooks(strict=True)
            self.notify()

    async def cook_action(self, address, action):
        async with self.cook_lock:
            if self.controls_fault:
                raise HomeAssistantError("Cook control stopped after a hub alert; inspect the app")
            if action not in ("acknowledge", "finish"):
                raise HomeAssistantError("This cook action is not enabled")
            await self.refresh_cooks(strict=True)
            cook = self.cook_for(address)
            if not cook:
                raise HomeAssistantError("No active cook on this probe")
            device = cook["hub_id"]
            sid = cook["session_id"]
            if action == "acknowledge":
                state = cook.get("state_notification", {})
                nid = state.get("notification_id")
                if state.get("is_running") is not False or not nid:
                    raise HomeAssistantError("Wait for a paused step before continuing")
                if not any(
                    x.get("notification_id") == nid
                    for x in cook.get("cooking_state_notifications", [])
                ):
                    raise HomeAssistantError("Current step is not yet fully loaded")
                await self.request(
                    device,
                    "start-notification/cooking-state",
                    {"session_id": sid, "notification_id": nid},
                )
            else:
                before = {
                    s["session_id"] for s in self.sessions.values() if s.get("hub_id") == device
                }
                await self.request(device, "end-session", {"session_id": sid})
                await self.refresh_cooks(strict=True)
                after = {
                    s["session_id"] for s in self.sessions.values() if s.get("hub_id") == device
                }
                if after != before - {sid}:
                    raise HomeAssistantError(
                        "End cook result differs from expected; inspect the app"
                    )
            await self.refresh_cooks(strict=True)
            self.notify()

    def cook_event(self, device, payload, topic):
        event_id = (device, payload.get("time_stamp"), payload.get("request_id"), topic)
        if event_id in self.seen_events:
            return
        self.seen_events.add(event_id)
        if len(self.seen_events) > 300:
            self.seen_events = {event_id}
        data = payload.get("data", {})
        sid = data.get("session_id")
        cook = self.sessions.get(sid, {})
        triggered = data.get("triggered_notification", {})
        if not isinstance(triggered, dict):
            triggered = {}
        nid = triggered.get("notification_id") or data.get("notification_id")
        steps = cook.get("cooking_state_notifications", []) + cook.get("session_notifications", [])
        step = next((x for x in steps if x.get("notification_id") == nid), {})
        message = (
            triggered.get("description")
            or data.get("description")
            or data.get("message")
            or step.get("description")
            or topic.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ")
        )
        name = cook.get("name", "CHEF iQ cook")
        self.hass.bus.async_fire(
            "chef_iq_cook_notification",
            {
                "session_id": sid,
                "cook_name": name,
                "notification_id": nid,
                "message": str(message),
                "notification_category": triggered.get(
                    "notification_category",
                    data.get("notification_category", step.get("notification_category")),
                ),
            },
        )
        persistent_notification.async_create(
            self.hass,
            str(message),
            title=name,
            notification_id="chef_iq_"
            + str(sid or device)
            + "_"
            + str(nid or topic.rsplit("/", 1)[-1]),
        )
        self.hass.async_create_task(self.refresh_cooks())

    @callback
    def receive(self, topic, payload):
        if payload.get("device_id") not in {d["device_id"] for d in self.devices}:
            return
        device = payload["device_id"]
        if "/res/" in topic:
            future = self.pending.get(payload.get("request_id"))
            if future and not future.done():
                future.set_result(payload)
        if "/evt/" in topic:
            if "system_alert" in payload.get("data", {}):
                self.controls_fault = True
            self.cook_event(device, payload, topic)
            return
        data = payload.get("data", {})
        now = time.time()
        if not isinstance(data, dict):
            return
        if payload.get("status", {}).get("code") == 0 and "user_info" in data:
            self.hub_state[device] = data
        if "sessions" in data:
            previous = {k: v for k, v in self.sessions.items() if v.get("hub_id") == device}
            for k in previous:
                self.sessions.pop(k, None)
            for cook in data["sessions"]:
                sid = cook.get("session_id")
                if sid:
                    self.sessions[sid] = {
                        **previous.get(sid, {}),
                        **cook,
                        "hub_id": device,
                        "updated_at": now,
                    }
        for probe in data.get("probes", []):
            if not isinstance(probe, dict):
                continue
            address = str(probe.get("address", "")).upper()
            compact = address.replace(":", "").replace("-", "")
            if len(compact) != 12 or any(x not in "0123456789ABCDEF" for x in compact):
                continue
            address = ":".join(compact[i : i + 2] for i in range(0, 12, 2))
            t = timestamp(probe.get("time_stamp"))
            if t is None or t > now + 10 or now - t > 180:
                continue
            previous = self.probes.get(address)
            if previous and t < previous["sample_timestamp"]:
                continue
            self.probes[address] = {
                **probe,
                "address": address,
                "sample_timestamp": t,
                "received_at": now,
                "hub_id": device,
            }
        self.notify()

    async def run(self):
        session = async_get_clientsession(self.hass)
        backoff = 5
        while not self.stop_event.is_set():
            try:
                auth = await refresh(
                    session,
                    self.entry.data["firebase_api_key"],
                    self.entry.data["refresh_token"],
                )
                new = auth.get("refresh_token", self.entry.data["refresh_token"])
                if new != self.entry.data["refresh_token"]:
                    self.hass.config_entries.async_update_entry(
                        self.entry, data={**self.entry.data, "refresh_token": new}
                    )
                headers = {
                    "Authorization": "Bearer " + auth["id_token"],
                    "ciq-region": "US",
                    "Accept-Language": "en-US",
                }
                self.auth_headers = headers
                self.user_id = auth.get("user_id")
                devices = await json_request(
                    session,
                    "https://devices-api.chefiq.com/v1/devices",
                    headers=headers,
                )
                self.devices = devices["data"]
                identity = await json_request(
                    session, "https://auth-api.chefiq.com/v2/token", {}, headers
                )
                creds = await json_request(
                    session,
                    "https://cognito-identity.us-east-1.amazonaws.com/",
                    {
                        "IdentityId": identity["cognito_id"],
                        "Logins": {"cognito-identity.amazonaws.com": identity["cognito_token"]},
                    },
                    {
                        "Content-Type": "application/x-amz-json-1.1",
                        "X-Amz-Target": "AWSCognitoIdentityService.GetCredentialsForIdentity",
                    },
                )
                self.last_error = None
                backoff = 5
                await stream(
                    session,
                    identity["cognito_id"],
                    self.devices,
                    creds["Credentials"],
                    "iot.chefiq.com",
                    self.receive,
                    self.connection,
                    self.stop_event,
                    self.ready,
                )
            except asyncio.CancelledError:
                raise
            except AuthError:
                self.last_error = "authentication_failed"
                _LOGGER.warning(
                    "CHEF iQ cloud authentication failed; reauthenticate the integration"
                )
                self.entry.async_start_reauth(self.hass)
                return
            except Exception as err:
                # Do not log raw HTTP URLs, signed WebSocket URLs, tokens, or payloads.
                self.last_error = type(err).__name__
                _LOGGER.warning("CHEF iQ cloud disconnected (%s); retrying", type(err).__name__)
            finally:
                self.connection(False)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 120)
