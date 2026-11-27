"""Exercise the token refresh endpoint with offline responses."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from aiohttp import ClientConnectionError

path = Path(__file__).resolve().parents[1] / "custom_components/chef_iq_cloud/cloud.py"
spec = importlib.util.spec_from_file_location("cloud", path)
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


def session_with_response(status, payload):
    session = MagicMock()
    response = session.post.return_value.__aenter__.return_value
    response.status = status
    response.json = AsyncMock(return_value=payload)
    return session


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_returns_rotated_credentials(self):
        data = {"id_token": "id", "refresh_token": "rotated", "user_id": "user"}
        result = await cloud.refresh(session_with_response(200, data), "key", "original")
        self.assertEqual(result, data)

    async def test_explicit_token_rejection_raises_auth_error(self):
        for status, error in (
            (400, {"message": "INVALID_REFRESH_TOKEN"}),
            (401, {"message": "TOKEN_EXPIRED"}),
            (400, "invalid_grant"),
        ):
            with self.subTest(status=status, error=error), self.assertRaises(cloud.AuthError):
                await cloud.refresh(session_with_response(status, {"error": error}), "key", "token")

    async def test_other_responses_use_the_retry_path(self):
        for status, payload in (
            (429, {"error": {"message": "INVALID_REFRESH_TOKEN"}}),
            (503, {"error": {"message": "TOKEN_EXPIRED"}}),
            (400, {"error": {"message": "INVALID_GRANT_TYPE"}}),
            (401, {"error": {"message": "API_KEY_INVALID"}}),
            (401, {"error": {"message": []}}),
            (401, {}),
            (200, {}),
            (200, {"id_token": 1}),
            (200, {"id_token": "id", "refresh_token": None}),
            (200, []),
        ):
            with self.subTest(status=status, payload=payload):
                with self.assertRaises(cloud.CloudError) as caught:
                    await cloud.refresh(session_with_response(status, payload), "key", "token")
                self.assertNotIsInstance(caught.exception, cloud.AuthError)

    async def test_invalid_json_and_network_errors_are_retryable(self):
        for error in (ValueError(), ClientConnectionError(), TimeoutError()):
            with self.subTest(error=type(error).__name__):
                session = session_with_response(400, None)
                session.post.return_value.__aenter__.return_value.json.side_effect = error
                with self.assertRaises(cloud.CloudError) as caught:
                    await cloud.refresh(session, "key", "token")
                self.assertNotIsInstance(caught.exception, cloud.AuthError)


if __name__ == "__main__":
    unittest.main()
