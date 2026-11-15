"""App cook-history API used by synchronized manual cook starts.

Recovered from Android 5.6.0: startCookSaga -> postHistory, followed by
getSessionsCookingHistoryJoin. A history link does not prove phone visibility.
"""

from copy import deepcopy
from urllib.parse import urlencode

from .cloud import CloudError, json_request

USERS = "https://users-api.chefiq.com/v1"


def history_body(app_data, model_number, device_id, device_name, session_id):
    """Build the REST record from app data, never the transformed hub payload."""
    data = deepcopy(app_data)
    category = data.pop("cooking_category")
    if category != 2:
        raise ValueError("Only manual cook creation is implemented")
    cooking_key = data.pop("cooking_key", None)
    for key in ("state", "ert_model", "notification_key", "auto_cancel"):
        data.pop(key, None)
    data.update(device_id=device_id, device_name=device_name, session_id=session_id)
    result = {"type": category, "model_number": model_number, "data": data}
    if cooking_key is not None:
        result["cooking_key"] = cooking_key
    return result


def matching_link(response, session_id, user_id):
    """Only accept the exact session/account link; reject ambiguous results."""
    rows = response.get("data") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        raise CloudError("Invalid cook-history response")
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("session_id") == session_id
        and row.get("user_id") == user_id
        and row.get("cooking_history_id")
    ]
    if len(matches) > 1:
        raise CloudError("Ambiguous cook-history link")
    return matches[0] if matches else None


class HistoryClient:
    def __init__(self, session, headers):
        self.session = session
        self.headers = headers

    async def links(self, session_id):
        return await json_request(
            self.session,
            USERS + "/sessions-cooking-history/?" + urlencode({"session_id": session_id}),
            headers=self.headers,
        )

    async def create(self, body):
        # No automatic retry: a timed-out POST may already have succeeded.
        return await json_request(self.session, USERS + "/cooking-history", body, self.headers)
