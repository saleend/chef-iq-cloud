import sys, types, importlib.util, asyncio, time, unittest
import importlib
from unittest.mock import AsyncMock, Mock
from pathlib import Path


def module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


class HAError(Exception):
    pass


module("homeassistant")
module("homeassistant.core", callback=lambda f: f)
module(
    "homeassistant.const",
    Platform=types.SimpleNamespace(SENSOR="sensor", NUMBER="number", TEXT="text", BUTTON="button"),
    EVENT_HOMEASSISTANT_STOP="stop",
)
module("homeassistant.helpers")
module("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda h: None)
module("homeassistant.helpers.dispatcher", async_dispatcher_send=lambda *a: None)
module("homeassistant.helpers.event", async_track_time_interval=lambda *a: None)


class FakeStore:
    def __init__(self, *a):
        self.data = None

    async def async_save(self, data):
        self.data = data


module("homeassistant.helpers.storage", Store=FakeStore)
module("homeassistant.exceptions", HomeAssistantError=HAError)
module(
    "homeassistant.components",
    persistent_notification=types.SimpleNamespace(async_create=lambda *a, **k: None),
)
p = Path("custom_components/chef_iq_cloud")
spec = importlib.util.spec_from_file_location(
    "chef_iq_cloud", p / "__init__.py", submodule_search_locations=[str(p)]
)
c = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = c
spec.loader.exec_module(c)


class Tests(unittest.IsolatedAsyncioTestCase):
    def manager(self, *, controls=False):
        h = types.SimpleNamespace()
        options = {c.CONF_ENABLE_COOK_CONTROLS: True} if controls else {}
        e = types.SimpleNamespace(entry_id="test", options=options)
        m = c.Manager(h, e)
        m.devices = [{"device_id": "hub"}]
        return m

    async def test_disabled_controls_block_writes_from_legacy_and_opted_out_entries(self):
        for options in (
            {"cook_settings": {"A": {"target": 150}}},
            {c.CONF_ENABLE_COOK_CONTROLS: False},
        ):
            with self.subTest(options=options):
                m = self.manager()
                m.entry.options = options
                m.connected = True
                m.sender = AsyncMock()
                with self.assertRaisesRegex(HAError, "Enable cook controls"):
                    await m.start_cook("A")
                for action in ("acknowledge", "finish"):
                    with self.assertRaisesRegex(HAError, "Enable cook controls"):
                        await m.cook_action("A", action)
                with self.assertRaisesRegex(HAError, "Enable cook controls"):
                    await m.request("hub", "start-session", {})
                with self.assertRaisesRegex(HAError, "Enable cook controls"):
                    m.set_setting("A", "target", 150)
                m.sender.assert_not_called()

    async def test_disabling_controls_before_history_write_blocks_post(self):
        m = self.manager(controls=True)
        session = Mock()
        history = c.HistoryClient(session, {}, m.require_cook_controls)
        m.entry.options[c.CONF_ENABLE_COOK_CONTROLS] = False
        with self.assertRaisesRegex(HAError, "Enable cook controls"):
            await history.create({})
        session.request.assert_not_called()

    async def test_control_platforms_require_opt_in_and_remove_retired_button(self):
        module("homeassistant.helpers.entity", Entity=object)
        module("homeassistant.components.button", ButtonEntity=object)
        module(
            "homeassistant.components.number",
            NumberEntity=object,
            NumberMode=types.SimpleNamespace(BOX="box"),
        )
        module(
            "homeassistant.components.text",
            TextEntity=object,
            TextMode=types.SimpleNamespace(TEXT="text"),
        )
        registry = Mock()
        old = types.SimpleNamespace(
            platform=c.DOMAIN, domain="button", unique_id="A_cook_cancel", entity_id="button.old"
        )
        current = types.SimpleNamespace(
            platform=c.DOMAIN, domain="button", unique_id="A_cook_start", entity_id="button.start"
        )
        other_platform = types.SimpleNamespace(
            platform="other", domain="button", unique_id=old.unique_id, entity_id="button.other"
        )
        other_domain = types.SimpleNamespace(
            platform=c.DOMAIN, domain="sensor", unique_id=old.unique_id, entity_id="sensor.other"
        )
        entries_for_config = Mock(return_value=[old, current, other_platform, other_domain])
        er = module(
            "homeassistant.helpers.entity_registry",
            async_get=lambda hass: registry,
            async_entries_for_config_entry=entries_for_config,
        )
        sys.modules["homeassistant.helpers"].entity_registry = er
        listeners = []
        sys.modules["homeassistant.helpers.dispatcher"].async_dispatcher_connect = (
            lambda hass, signal, discover: listeners.append(discover)
        )
        m = self.manager()
        m.entry.async_on_unload = Mock()
        m.hass.data = {c.DOMAIN: {m.entry.entry_id: m}}
        m.probes["A"] = {"number": 1}
        entities = []
        platforms = [
            importlib.import_module(f"chef_iq_cloud.{name}")
            for name in ("number", "text", "button")
        ]
        for platform in platforms:
            await platform.async_setup_entry(m.hass, m.entry, entities.extend)
        self.assertEqual(entities, [])
        self.assertEqual(listeners, [])
        entries_for_config.assert_called_once_with(registry, m.entry.entry_id)
        registry.async_remove.assert_called_once_with("button.old")

        m.entry.options[c.CONF_ENABLE_COOK_CONTROLS] = True
        for platform in platforms:
            await platform.async_setup_entry(m.hass, m.entry, entities.extend)
        self.assertCountEqual(
            [entity.key for entity in entities],
            [
                "target",
                "flip",
                "wrap",
                "rest",
                "name",
                "start",
                "acknowledge",
                "finish",
                "reconcile",
            ],
        )
        self.assertEqual(len(listeners), 3)
        m.entry.options[c.CONF_ENABLE_COOK_CONTROLS] = False
        m.probes["B"] = {"number": 2}
        for discover in listeners:
            discover()
        self.assertEqual(len(entities), 9)

    async def test_options_flow_defaults_off_and_preserves_saved_probe_settings(self):
        class ConfigFlow:
            def __init_subclass__(cls, domain):
                super().__init_subclass__()

            def async_show_form(self, **result):
                return result

        class OptionsFlowWithReload:
            def async_show_form(self, **result):
                return result

            def async_create_entry(self, **result):
                return result

        config_entries = module(
            "homeassistant.config_entries",
            ConfigFlow=ConfigFlow,
            OptionsFlowWithReload=OptionsFlowWithReload,
        )
        sys.modules["homeassistant"].config_entries = config_entries
        module("homeassistant.data_entry_flow", AbortFlow=Exception)
        class TextSelector:
            def __init__(self, config):
                self.config = config

            def __call__(self, value):
                return value

        module(
            "homeassistant.helpers.selector",
            TextSelector=TextSelector,
            TextSelectorConfig=lambda **kwargs: kwargs,
            TextSelectorType=types.SimpleNamespace(PASSWORD="password"),
        )
        flow_module = importlib.import_module("chef_iq_cloud.config_flow")
        config_flow = flow_module.ConfigFlow()
        for step in (config_flow.async_step_user, config_flow.async_step_reauth_confirm):
            form = await step()
            schema = form["data_schema"]
            selector = next(value for key, value in schema.schema.items() if key == "password")
            self.assertIsInstance(selector, TextSelector)
            self.assertEqual(selector.config["type"], "password")
            self.assertEqual(
                schema({"email": "test@example.com", "password": "test-password"})["password"],
                "test-password",
            )
        entry = self.manager().entry
        entry.options = {"cook_settings": {"A": {"target": 150}}}
        flow = flow_module.ConfigFlow.async_get_options_flow(entry)
        self.assertIsInstance(flow, OptionsFlowWithReload)
        flow.config_entry = entry
        option = c.CONF_ENABLE_COOK_CONTROLS
        form = await flow.async_step_init()
        self.assertFalse(form["data_schema"]({})[option])
        result = await flow.async_step_init({option: True})
        self.assertEqual(result["data"], {**entry.options, option: True})
        entry.options = result["data"]
        form = await flow.async_step_init()
        self.assertTrue(form["data_schema"]({})[option])
        result = await flow.async_step_init({option: False})
        self.assertEqual(result["data"], {"cook_settings": {"A": {"target": 150}}, option: False})

    async def test_merge_and_end_sessions(self):
        m = self.manager()
        m.receive(
            "/res/x",
            {
                "device_id": "hub",
                "status": {"code": 0},
                "data": {
                    "sessions": [
                        {
                            "session_id": "s",
                            "probe_address": "A",
                            "cooking_state_notifications": [{"description": "flip"}],
                        }
                    ]
                },
            },
        )
        m.receive(
            "/dt/x",
            {
                "device_id": "hub",
                "data": {
                    "sessions": [{"session_id": "s", "probe_address": "A", "target_temp": 165}]
                },
            },
        )
        self.assertEqual(m.cook_for("A")["cooking_state_notifications"][0]["description"], "flip")
        m.receive("/dt/x", {"device_id": "hub", "data": {"sessions": []}})
        self.assertIsNone(m.cook_for("A"))

    async def test_acknowledgement_correlated(self):
        m = self.manager()
        m.connected = True

        async def send(device, command, data, rid):
            m.receive(
                "/res/" + rid,
                {
                    "device_id": "hub",
                    "request_id": rid,
                    "status": {"code": 0},
                    "data": {},
                },
            )

        m.sender = send
        r = await m.request("hub", "get-state", {})
        self.assertEqual(r["status"]["code"], 0)
        self.assertFalse(m.pending)

    async def test_nested_hub_notification(self):
        m = self.manager()
        events = []
        m.hass.bus = types.SimpleNamespace(async_fire=lambda event, data: events.append(data))
        m.hass.async_create_task = lambda task: task.close()
        m.sessions = {"s": {"name": "Test"}}
        m.cook_event(
            "hub",
            {
                "time_stamp": 123,
                "data": {
                    "session_id": "s",
                    "notification_key": "secret",
                    "triggered_notification": {
                        "notification_id": "n",
                        "description": "remove your food from heat",
                        "notification_category": 0,
                    },
                },
            },
            "/evt/notification/cooking-state",
        )
        self.assertEqual(events[0]["message"], "remove your food from heat")
        self.assertEqual(events[0]["notification_id"], "n")
        self.assertNotIn("notification_key", events[0])

    async def test_control_fault_blocks_all_writes(self):
        m = self.manager(controls=True)
        m.controls_fault = True
        with self.assertRaises(HAError):
            await m.start_cook("A")
        for action in ["acknowledge", "finish", "cancel"]:
            with self.assertRaises(HAError):
                await m.cook_action("A", action)

    async def test_continue_uses_current_loaded_paused_step_only(self):
        m = self.manager(controls=True)
        calls = []
        m.sessions = {
            "s": {
                "session_id": "s",
                "hub_id": "hub",
                "probe_address": "a",
                "state_notification": {"notification_id": "n", "is_running": False},
                "cooking_state_notifications": [{"notification_id": "n"}],
            }
        }

        async def refresh(strict=False):
            pass

        async def request(device, command, data):
            calls.append((command, data))

        m.refresh_cooks = refresh
        m.request = request
        await m.cook_action("A", "acknowledge")
        self.assertEqual(
            calls,
            [
                (
                    "start-notification/cooking-state",
                    {"session_id": "s", "notification_id": "n"},
                )
            ],
        )
        m.sessions["s"]["state_notification"]["is_running"] = True
        with self.assertRaises(HAError):
            await m.cook_action("A", "acknowledge")
        self.assertEqual(len(calls), 1)

    async def test_end_only_selected_session_and_verify_others(self):
        m = self.manager(controls=True)
        calls = []
        m.sessions = {
            "s": {"session_id": "s", "hub_id": "hub", "probe_address": "a"},
            "pork": {"session_id": "pork", "hub_id": "hub", "probe_address": "b"},
        }

        async def refresh(strict=False):
            pass

        async def request(device, command, data):
            calls.append((command, data))
            m.sessions.pop(data["session_id"])

        m.refresh_cooks = refresh
        m.request = request
        await m.cook_action("A", "finish")
        self.assertEqual(calls, [("end-session", {"session_id": "s"})])
        self.assertIn("pork", m.sessions)

    async def test_manager_start_connects_history_and_journal_without_auto_continue(
        self,
    ):
        m = self.manager(controls=True)
        m.devices[0]["model_number"] = "CQ60-3C-HUB"
        m.auth_headers = {}
        m.user_id = "user"
        m.auth_headers = {"Authorization": "test"}
        m.probes["A"] = {"hub_id": "hub", "number": 2, "name": "Probe 2"}
        m.settings["A"] = {
            "name": "Test",
            "target": 120,
            "flip": 0,
            "wrap": 0,
            "rest": 0,
        }
        state = {
            "sessions": [],
            "probes": [{"address": "a", "is_active": True}],
            "user_info": {"notification_key": "private"},
        }
        calls = []
        posts = []

        async def request(device, command, data):
            calls.append(command)
            if command == "start-session":
                state["sessions"].append(data)
            return {"data": state}

        m.request = request

        class History:
            def __init__(self, *a):
                pass

            async def links(self, sid):
                return {
                    "data": [
                        {
                            "session_id": sid,
                            "user_id": "user",
                            "cooking_history_id": "h",
                        }
                    ]
                    if posts
                    else []
                }

            async def create(self, body):
                posts.append(body)

        original = c.HistoryClient
        c.HistoryClient = History
        try:
            await m.start_cook("A")
        finally:
            c.HistoryClient = original
        self.assertEqual(calls.count("start-session"), 1)
        self.assertNotIn("start-notification/cooking-state", calls)
        self.assertEqual(posts[0]["data"]["probe_address"], "a")
        self.assertNotIn("notification_key", posts[0]["data"])
        self.assertEqual(len(posts[0]["data"]["cooking_state_notifications"]), 1)
        self.assertEqual(next(iter(m.store.data.values()))["phase"], "history_link_verified")

    async def test_recovery_requires_full_responses_from_every_hub(self):
        m = self.manager()
        m.connected = True
        m.auth_headers = {"Authorization": "test"}
        m.user_id = "user"
        m.cook_journal = {"s": {"phase": "hub_start_pending"}}

        async def request(*args):
            return {"data": {}}

        m.request = request
        with self.assertRaises(HAError):
            await m.reconcile_starts()
        self.assertIsNone(m.store.data)
        self.assertEqual(m.cook_journal["s"]["phase"], "hub_start_pending")

    async def test_recovery_checks_absence_with_read_commands_only(self):
        m = self.manager()
        m.connected = True
        m.auth_headers = {"Authorization": "test"}
        m.user_id = "user"
        m.cook_journal = {"s": {"phase": "hub_start_pending"}}
        calls = []

        async def request(device, command, data):
            calls.append(command)
            return {"data": {"sessions": []}}

        m.request = request
        await m.reconcile_starts()
        self.assertEqual(calls, ["get-state"])
        self.assertEqual(m.store.data["s"]["phase"], "checked_absent")


class RegistryTests(unittest.TestCase):
    def test_registry_search_finds_official_ble_among_multiple_matching_devices(self):
        module(
            "homeassistant.components.sensor",
            SensorEntity=object,
            SensorDeviceClass=types.SimpleNamespace(TEMPERATURE="temperature"),
            SensorStateClass=types.SimpleNamespace(MEASUREMENT="measurement"),
        )
        sys.modules["homeassistant.const"].UnitOfTemperature = types.SimpleNamespace(CELSIUS="°C")
        sys.modules["homeassistant.helpers.dispatcher"].async_dispatcher_connect = lambda *a: None
        official = types.SimpleNamespace(
            platform="chef_iq",
            domain="sensor",
            entity_id="sensor.official_food_temperature",
            unique_id="food_temperature",
        )
        foreign = types.SimpleNamespace(
            platform="other",
            domain="sensor",
            entity_id="sensor.other_food_temperature",
            unique_id="food_temperature",
        )
        er = module(
            "homeassistant.helpers.entity_registry",
            async_get=lambda h: types.SimpleNamespace(async_get=lambda eid: None),
            async_entries_for_device=lambda registry, did: (
                [official] if did == "official" else [foreign]
            ),
        )
        dr = module(
            "homeassistant.helpers.device_registry",
            async_get=lambda h: types.SimpleNamespace(
                async_get_devices=lambda **kwargs: [
                    types.SimpleNamespace(id="foreign"),
                    types.SimpleNamespace(id="official"),
                ]
            ),
        )
        sys.modules["homeassistant.helpers"].entity_registry = er
        sys.modules["homeassistant.helpers"].device_registry = dr
        sensor = importlib.import_module("chef_iq_cloud.sensor")
        probe = sensor.ProbeSensor(
            types.SimpleNamespace(probes={"AA": {"number": 2}}),
            "AA",
            "food_temperature",
            "combined",
        )
        probe.hass = types.SimpleNamespace()
        self.assertEqual(probe.ble_entity(), official.entity_id)


unittest.main()
