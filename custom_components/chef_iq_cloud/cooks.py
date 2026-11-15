"""Cook models and payloads shared by the UI and hub commands."""

import uuid


def current_step_status(cook):
    """Distinguish the terminal cleanup timer from an actual cooking step."""
    current = cook.get("state_notification", {})
    steps = cook.get("cooking_state_notifications", [])
    step = next(
        (x for x in steps if x.get("notification_id") == current.get("notification_id")),
        {},
    )
    complete = bool(
        step
        and steps
        and step is steps[-1]
        and step.get("timer") == 300
        and "notification_category" not in step
        and not step.get("description")
    )
    remaining = current.get("remaining_time")
    return {
        "current_step": "Cook complete" if complete else step.get("description", ""),
        "cook_complete": complete,
        "step_remaining_seconds": None if complete or remaining == 4294967295 else remaining,
    }


def public_cook(cook):
    keys = (
        "session_id",
        "name",
        "target_temp",
        "cooking_category",
        "estimated_cooking_time",
        "est_remaining_cooking_time",
        "remaining_cooking_time",
        "total_elapsed_time",
        "operating_warning",
        "internal_temp",
        "ambient_temp",
        "state_notification",
        "session_notification_status",
        "cooking_state_notifications",
        "session_notifications",
    )
    result = {k: cook[k] for k in keys if k in cook}
    for key in (
        "estimated_cooking_time",
        "est_remaining_cooking_time",
        "remaining_cooking_time",
        "total_elapsed_time",
    ):
        if result.get(key) == 4294967295:
            result[key] = None
    if isinstance(result.get("state_notification"), dict):
        result["state_notification"] = dict(result["state_notification"])
        if result["state_notification"].get("remaining_time") == 4294967295:
            result["state_notification"]["remaining_time"] = None
    return result


def start_payload(address, number, name, target, notification_key, flip=None, wrap=None, rest=0):
    if not 32 <= target <= 212:
        raise ValueError("Target must be between 32 and 212 °F")
    if not name.strip() or len(name) > 80:
        raise ValueError("Enter a cook name (1–80 characters)")

    def step(category, description, audio, temp=None, timer=None, first=False):
        d = {
            "notification_id": str(uuid.uuid4()),
            "notification_category": category,
            "description": description,
            "audio_clips": ["cookingalert_t.mp3", f"forprobe{number}.mp3", audio],
        }
        if temp is not None:
            d.update(condition={"internal_temp": {"gte": temp}}, reminder=60)
        if timer is not None:
            d.update(timer=timer, trigger_start=6)
        if first:
            d["trigger_start"] = 10
        return d

    steps = []
    for temp, category, description, audio in [
        (flip, 1, "flip your food", "flipfood.mp3"),
        (wrap, 5, "wrap your food in foil", "wrapfood.mp3"),
    ]:
        if temp is None:
            continue
        if not 32 <= temp < target:
            raise ValueError("Flip/wrap temperature must be below the target")
        steps.append(step(category, description, audio, temp=temp))
    steps.sort(key=lambda x: x["condition"]["internal_temp"]["gte"])
    steps.append(step(0, "remove your food from heat", "removefood.mp3", temp=target))
    steps[0]["trigger_start"] = 10
    if rest:
        if not 0 < rest <= 240:
            raise ValueError("Rest time must be between 0 and 240 minutes")
        d = step(
            11,
            "move to the next step; the rest timer is complete",
            "cookcomplete_t.mp3",
            timer=int(rest * 60),
        )
        d["audio_clips"] = ["cookcomplete_t.mp3"]
        steps.append(d)
    steps.append({"notification_id": str(uuid.uuid4()), "timer": 300})
    # The official app matches addresses case-sensitively against lowercase hub data.
    return {
        "session_id": str(uuid.uuid4()),
        "probe_address": address.lower(),
        "notification_key": notification_key,
        "target_temp": target,
        "auto_cancel": True,
        "cooking_category": 2,
        "name": name.strip(),
        "cooking_state_notifications": steps,
        "session_notifications": [],
    }
