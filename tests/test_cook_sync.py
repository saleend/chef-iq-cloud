"""Offline failure-boundary tests; no credentials, network or hub commands."""

import asyncio
import importlib
from pathlib import Path
import sys
import types
import unittest
from copy import deepcopy

root = Path(__file__).resolve().parents[1]
package = types.ModuleType("sync_test_component")
package.__path__ = [str(root / "custom_components/chef_iq_cloud")]
sys.modules[package.__name__] = package
history = importlib.import_module(package.__name__ + ".history")
sync = importlib.import_module(package.__name__ + ".cook_sync")


class FakeHistory:
    def __init__(self):
        self.rows = []
        self.posts = 0
        self.timeout = False

    async def links(self, sid):
        return {"data": deepcopy(self.rows)}

    async def create(self, body):
        self.posts += 1
        self.rows = [
            {
                "session_id": body["data"]["session_id"],
                "user_id": "user",
                "cooking_history_id": "history",
            }
        ]
        if self.timeout:
            raise asyncio.TimeoutError()


class SyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.payload = {
            "session_id": "session",
            "probe_address": "AA:BB",
            "target_temp": 100,
            "name": "Test",
            "cooking_category": 2,
        }
        self.body = history.history_body(self.payload, "CQ60-3C-HUB", "hub", "Hub", "session")
        self.state = {
            "sessions": [],
            "probes": [{"address": "AA:BB", "is_active": True}],
        }
        self.saved = []
        self.commands = []
        self.api = FakeHistory()
        self.confirm = True

    async def read(self):
        return deepcopy(self.state)

    async def save(self, data):
        self.saved.append(deepcopy(data))

    async def send(self, payload):
        self.assertEqual(self.saved[-1]["session"]["phase"], "hub_start_pending")
        self.commands.append(payload)
        if self.confirm:
            self.state["sessions"].append(deepcopy(payload))

    def transaction(self, journal=None):
        return sync.StartTransaction(
            self.read, self.send, self.api, self.save, journal or {}, "user"
        )

    async def test_success_confirms_link_without_starting_a_step(self):
        result = await self.transaction().start(self.payload, self.body)
        self.assertEqual(result["sync_status"], "history_link_verified")
        self.assertFalse(result["phone_visibility_verified"])
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.api.posts, 1)

    async def test_any_existing_cook_blocks_before_write(self):
        self.state["sessions"] = [{"session_id": "real-cook", "probe_address": "other"}]
        with self.assertRaises(sync.CookSyncError):
            await self.transaction().start(self.payload, self.body)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.saved, [])

    async def test_missing_or_inactive_probe_blocks(self):
        for probes in ([], [{"address": "AA:BB", "is_active": False}]):
            self.state["probes"] = probes
            with self.assertRaises(sync.CookSyncError):
                await self.transaction().start(self.payload, self.body)
        self.assertEqual(self.commands, [])

    async def test_unconfirmed_hub_never_posts_history_or_retries(self):
        self.confirm = False
        tx = self.transaction()
        for _ in range(2):
            with self.assertRaises(sync.CookSyncError):
                await tx.start(self.payload, self.body)
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.api.posts, 0)

    async def test_history_timeout_remains_uncertain_across_restart(self):
        self.api.timeout = True
        with self.assertRaises(asyncio.TimeoutError):
            await self.transaction().start(self.payload, self.body)
        self.assertEqual(self.saved[-1]["session"]["phase"], "history_post_pending")
        self.state["sessions"] = []
        with self.assertRaises(sync.CookSyncError):
            await self.transaction(self.saved[-1]).start(self.payload, self.body)
        self.assertEqual(self.api.posts, 1)
        self.assertEqual(len(self.commands), 1)

    async def test_existing_link_is_not_posted_again(self):
        self.api.rows = [{"session_id": "session", "user_id": "user", "cooking_history_id": "old"}]
        result = await self.transaction().start(self.payload, self.body)
        self.assertEqual(result["cooking_history_id"], "old")
        self.assertEqual(self.api.posts, 0)

    async def test_mismatched_history_blocks_before_command(self):
        self.body["data"]["target_temp"] = 99
        with self.assertRaises(sync.CookSyncError):
            await self.transaction().start(self.payload, self.body)
        self.assertEqual(self.commands, [])

    async def test_failed_journal_save_blocks_command(self):
        async def fail(data):
            raise OSError("disk unavailable")

        tx = sync.StartTransaction(self.read, self.send, self.api, fail, {}, "user")
        with self.assertRaises(OSError):
            await tx.start(self.payload, self.body)
        self.assertEqual(self.commands, [])

    async def test_explicit_snapshot_override_preserves_existing_cook(self):
        self.state["sessions"] = [{"session_id": "real", "probe_address": "CC:DD"}]
        await self.transaction().start(
            self.payload, self.body, allowed_existing_session_ids=["real"]
        )
        self.assertEqual({x["session_id"] for x in self.state["sessions"]}, {"real", "session"})

    async def test_override_cannot_overwrite_existing_probe(self):
        self.state["sessions"] = [{"session_id": "real", "probe_address": "AA:BB"}]
        with self.assertRaises(sync.CookSyncError):
            await self.transaction().start(
                self.payload, self.body, allowed_existing_session_ids=["real"]
            )
        self.assertEqual(self.commands, [])

    async def test_recovery_verifies_existing_link_without_reposting(self):
        self.api.rows = [{"session_id": "session", "user_id": "user", "cooking_history_id": "h"}]
        journal = {"session": {"phase": "history_post_pending"}}
        state = {"sessions": [{"session_id": "session"}]}
        result = await sync.reconcile_journal(journal, state, self.api, "user")
        self.assertEqual(result["session"]["phase"], "history_link_verified")
        self.assertEqual(journal["session"]["phase"], "history_post_pending")
        self.assertEqual(self.api.posts, 0)

    async def test_recovery_leaves_active_unsynced_cook_blocked(self):
        journal = {"session": {"phase": "history_post_pending"}}
        result = await sync.reconcile_journal(
            journal, {"sessions": [{"session_id": "session"}]}, self.api, "user"
        )
        self.assertEqual(result, journal)
        self.assertEqual(self.api.posts, 0)

    async def test_recovery_marks_absent_without_any_hub_write(self):
        journal = {"session": {"phase": "hub_start_pending"}}
        result = await sync.reconcile_journal(journal, {"sessions": []}, self.api, "user")
        self.assertEqual(result["session"]["phase"], "checked_absent")
        self.assertEqual(self.api.posts, 0)
        self.assertEqual(self.commands, [])

    async def test_recovery_refuses_incomplete_hub_state(self):
        with self.assertRaises(sync.CookSyncError):
            await sync.reconcile_journal(
                {"session": {"phase": "hub_start_pending"}}, {}, self.api, "user"
            )


class HistoryTests(unittest.TestCase):
    def test_build_does_not_leak_transport_credentials_or_mutate_input(self):
        source = {
            "cooking_category": 2,
            "notification_key": "private",
            "ert_model": {},
            "state": {},
            "name": "Test",
            "session_notifications": [],
        }
        body = history.history_body(source, "CQ60", "hub", "Hub", "sid")
        self.assertNotIn("notification_key", body["data"])
        self.assertNotIn("cooking_category", body["data"])
        self.assertIn("notification_key", source)
        self.assertEqual(body["type"], 2)

    def test_wrong_session_and_account_are_not_proof_of_sync(self):
        for row in (
            {"session_id": "other", "user_id": "u"},
            {"session_id": "s", "user_id": "other"},
        ):
            row["cooking_history_id"] = "h"
            self.assertIsNone(history.matching_link({"data": [row]}, "s", "u"))
        row = {"session_id": "s", "user_id": "u", "cooking_history_id": "h"}
        with self.assertRaises(history.CloudError):
            history.matching_link({"data": [row, row]}, "s", "u")


if __name__ == "__main__":
    unittest.main()
