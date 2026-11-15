import importlib.util, unittest

p = "custom_components/chef_iq_cloud/cooks.py"
s = importlib.util.spec_from_file_location("cooks", p)
c = importlib.util.module_from_spec(s)
s.loader.exec_module(c)


class TestCooks(unittest.TestCase):
    def test_steps_and_audio(self):
        p = c.start_payload(
            "AA:BB:CC:DD:EE:FF", 5, "Test", 205, "private", flip=100, wrap=160, rest=30
        )
        ns = p["cooking_state_notifications"]
        self.assertEqual([n.get("notification_category") for n in ns], [1, 5, 0, 11, None])
        self.assertEqual(ns[0]["trigger_start"], 10)
        self.assertEqual(ns[3]["timer"], 1800)
        self.assertEqual(ns[1]["audio_clips"][1], "forprobe5.mp3")
        self.assertEqual(p["cooking_category"], 2)

    def test_rejects_invalid_settings(self):
        for kw in [
            {"target": 220},
            {"target": 150, "flip": 160},
            {"target": 165, "rest": 300},
            {"target": 165, "name": " "},
        ]:
            data = {
                "address": "a",
                "number": 0,
                "name": "test",
                "target": 165,
                "notification_key": "secret",
                **kw,
            }
            with self.assertRaises(ValueError):
                c.start_payload(**data)

    def test_no_secret_in_sensor(self):
        self.assertNotIn(
            "notification_key",
            c.public_cook({"name": "test", "notification_key": "secret", "hub_id": "private"}),
        )

    def test_independent_ids(self):
        a = c.start_payload("a", 0, "x", 165, "k")
        b = c.start_payload("a", 0, "x", 165, "k")
        self.assertNotEqual(a["session_id"], b["session_id"])

    def test_app_address_format(self):
        p = c.start_payload("AA:BB:CC:DD:EE:FF", 2, "Test", 120, "k")
        self.assertEqual(p["probe_address"], "aa:bb:cc:dd:ee:ff")

    def test_unknown_time_sentinel(self):
        raw = {
            "est_remaining_cooking_time": 4294967295,
            "state_notification": {"remaining_time": 4294967295},
        }
        result = c.public_cook(raw)
        self.assertIsNone(result["est_remaining_cooking_time"])
        self.assertIsNone(result["state_notification"]["remaining_time"])
        self.assertEqual(raw["state_notification"]["remaining_time"], 4294967295)

    def test_terminal_cleanup_is_complete_without_a_cooking_estimate(self):
        cook = {
            "state_notification": {"notification_id": "done", "remaining_time": 280},
            "cooking_state_notifications": [
                {"notification_id": "heat", "description": "remove"},
                {"notification_id": "done", "timer": 300},
            ],
        }
        result = c.current_step_status(cook)
        self.assertTrue(result["cook_complete"])
        self.assertEqual(result["current_step"], "Cook complete")
        self.assertIsNone(result["step_remaining_seconds"])

    def test_five_minute_rest_is_still_a_real_step(self):
        cook = {
            "state_notification": {"notification_id": "rest", "remaining_time": 250},
            "cooking_state_notifications": [
                {
                    "notification_id": "rest",
                    "timer": 300,
                    "notification_category": 11,
                    "description": "rest complete",
                }
            ],
        }
        result = c.current_step_status(cook)
        self.assertFalse(result["cook_complete"])
        self.assertEqual(result["step_remaining_seconds"], 250)

    def test_unknown_step_is_not_claimed_complete(self):
        self.assertFalse(
            c.current_step_status({"state_notification": {"notification_id": "missing"}})[
                "cook_complete"
            ]
        )


unittest.main()
