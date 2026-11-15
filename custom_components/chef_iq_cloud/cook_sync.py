"""Journaled start transaction shared by HA controls and offline tests.

Callbacks must provide fresh hub state and
durable journal writes. No retry, step activation, cancellation, or rollback is
performed here. Uncertain writes require inspection in the official app.
"""

import asyncio
from copy import deepcopy

from .history import matching_link

RESOLVED_PHASES = {"history_link_verified", "checked_absent"}


async def reconcile_journal(journal, state, history, user_id):
    """Explicit read-only recovery. Never send a hub command or history POST."""
    if not isinstance(state.get("sessions"), list):
        raise CookSyncError("Fresh full hub state is required")
    result = deepcopy(journal)
    active = {s.get("session_id") for s in state["sessions"]}
    for sid, record in result.items():
        if record.get("phase") in RESOLVED_PHASES:
            continue
        if sid not in active:
            record["phase"] = "checked_absent"
        elif matching_link(await history.links(sid), sid, user_id):
            record["phase"] = "history_link_verified"
    return result


class CookSyncError(Exception):
    pass


class StartTransaction:
    def __init__(self, read_state, send_start, history, save_journal, journal, user_id):
        self.read_state = read_state
        self.send_start = send_start
        self.history = history
        self.save_journal = save_journal
        self.journal = deepcopy(journal)
        self.user_id = user_id
        self.lock = asyncio.Lock()

    async def _record(self, session_id, phase):
        # Persist intent BEFORE each write. A restart must never replay it.
        self.journal[session_id] = {"phase": phase}
        await self.save_journal(deepcopy(self.journal))

    async def start(self, payload, body, *, allowed_existing_session_ids=()):
        async with self.lock:
            sid = payload.get("session_id")
            if not sid or body.get("data", {}).get("session_id") != sid:
                raise CookSyncError("Hub/history session identifiers must match")
            if body.get("type") != 2 or payload.get("cooking_category") != 2:
                raise CookSyncError("Only manual cooks are implemented")
            if any(
                body["data"].get(key) != payload.get(key)
                for key in ("probe_address", "target_temp", "name")
            ):
                raise CookSyncError("Hub/history cook details must match")
            if sid in self.journal or any(
                x.get("phase") not in RESOLVED_PHASES for x in self.journal.values()
            ):
                raise CookSyncError("Inspect the previous start in the app before retrying")
            before = await self.read_state()
            if not isinstance(before.get("sessions"), list):
                raise CookSyncError("Full hub state is required")
            existing = {x.get("session_id") for x in before["sessions"]}
            # Explicit, per-call override for a user-authorized live experiment.
            # Default still blocks every existing cook. Never overwrite its probe.
            if existing != set(allowed_existing_session_ids):
                raise CookSyncError("Existing cooks differ from the authorized test snapshot")
            if any(
                x.get("probe_address", "").upper() == payload.get("probe_address", "").upper()
                for x in before["sessions"]
            ):
                raise CookSyncError("Selected probe already has a cook")
            probes = [
                p
                for p in before.get("probes", [])
                if p.get("address", "").upper() == payload.get("probe_address", "").upper()
            ]
            if len(probes) != 1 or probes[0].get("is_active") is not True:
                raise CookSyncError("Selected probe must be active in fresh hub state")
            await self._record(sid, "hub_start_pending")
            # Exceptions deliberately leave the pending journal entry in place.
            await self.send_start(deepcopy(payload))
            after = await self.read_state()
            sessions = after.get("sessions")
            if (
                not isinstance(sessions, list)
                or len(sessions) != len(existing) + 1
                or {x.get("session_id") for x in sessions} != existing | {sid}
            ):
                raise CookSyncError("Hub state did not preserve existing cooks plus the new cook")
            cook = next(x for x in sessions if x.get("session_id") == sid)
            if (
                cook.get("session_id") != sid
                or cook.get("probe_address", "").upper() != payload["probe_address"].upper()
                or cook.get("target_temp") != payload.get("target_temp")
            ):
                raise CookSyncError("Hub cook does not match the requested cook")
            await self._record(sid, "hub_confirmed")
            # Check first so a preexisting history record is never duplicated.
            link = matching_link(await self.history.links(sid), sid, self.user_id)
            if link is None:
                await self._record(sid, "history_post_pending")
                await self.history.create(deepcopy(body))
                link = matching_link(await self.history.links(sid), sid, self.user_id)
            if link is None:
                raise CookSyncError("Cook exists on hub; app history link remains unverified")
            await self._record(sid, "history_link_verified")
            return {
                "session_id": sid,
                "cooking_history_id": link["cooking_history_id"],
                "sync_status": "history_link_verified",
                "phone_visibility_verified": False,
            }
